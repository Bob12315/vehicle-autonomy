"""Offline Mission scheduler that emits requests but never submits commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from contracts.core.primitives import RunId, SchemaVersion
from contracts.core.time import TimePoint
from contracts.decision import ActionDecision, ActionOutcome, EffectResult, ExitDecision, ExitReason, FailurePolicy
from contracts.effects.vehicle import EffectEnvelope, VehicleEffect
from contracts.world.ports import WorldQueryPort
from .mission import CompiledMission, CompiledStep


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    EXITING = "EXITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class StepResult:
    step_id: str
    attempt: int
    reason: ExitReason
    result: object = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RunUpdate:
    run_id: RunId
    status: RunStatus
    step_id: str | None
    attempt: int
    effects: tuple[EffectEnvelope, ...]
    results: tuple[StepResult, ...]
    error: str | None = None


class MissionRuntime:
    def __init__(
        self, compiled: CompiledMission, world: WorldQueryPort,
        run_id: RunId, *, max_snapshot_age_ns: int,
    ) -> None:
        if not isinstance(compiled, CompiledMission):
            raise TypeError("compiled must be CompiledMission")
        if isinstance(max_snapshot_age_ns, bool) or not isinstance(max_snapshot_age_ns, int) or max_snapshot_age_ns <= 0:
            raise ValueError("max_snapshot_age_ns must be positive")
        self._compiled = compiled
        self._world = world
        self._run_id = RunId(run_id)
        self._max_age_ns = max_snapshot_age_ns
        self._status = RunStatus.RUNNING
        self._index = 0
        self._attempt = 0
        self._instance = None
        self._pending: tuple[ExitReason, object, str | None] | None = None
        self._cancel_requested = False
        self._results: list[StepResult] = []
        self._effect_sequence = 0
        self._error: str | None = None
        self._emitted: dict[str, str] = {}
        self._effect_results: dict[str, EffectResult] = {}

    def record_effect_result(self, result: EffectResult) -> None:
        """Accept read-only command progress for an Effect emitted by this run."""
        if not isinstance(result, EffectResult) or self._emitted.get(result.effect_id) != result.action_instance_id:
            raise ValueError("result does not belong to this Mission run")
        self._effect_results[result.effect_id] = result

    def _step(self) -> CompiledStep | None:
        return self._compiled.steps[self._index] if self._index < len(self._compiled.steps) else None

    def _view(self, effects: tuple[EffectEnvelope, ...] = ()) -> RunUpdate:
        step = self._step()
        return RunUpdate(
            self._run_id, self._status, step.step.step_id if step else None,
            self._attempt, effects, tuple(self._results), self._error,
        )

    def view(self) -> RunUpdate:
        return self._view()

    def cancel(self) -> RunUpdate:
        if self._status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
            return self._view()
        self._cancel_requested = True
        if self._instance is None:
            self._status = RunStatus.CANCELLED
        else:
            self._pending = (ExitReason.CANCELLED, None, None)
            self._status = RunStatus.EXITING
        return self._view()

    def abort(self, reason: str) -> RunUpdate:
        """Fail closed when the outer runtime cannot safely advance an exit barrier."""
        if self._status not in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
            self._status = RunStatus.FAILED
            self._error = reason
            self._instance = None
        return self._view()

    def _envelopes(self, effects: tuple[VehicleEffect, ...], now: TimePoint) -> tuple[EffectEnvelope, ...]:
        step = self._step()
        assert step is not None
        allowed = step.registration.spec.effect_types
        if any(type(effect) not in allowed for effect in effects):
            raise TypeError(f"Action {step.step.action} emitted an undeclared effect")
        envelopes = []
        for effect in effects:
            self._effect_sequence += 1
            deadline = TimePoint(
                now.monotonic_ns + step.registration.spec.effect_ttl_ns,
                now.utc, now.clock_domain_id,
            )
            envelope = EffectEnvelope(
                SchemaVersion(1, 0), f"{self._run_id}:effect:{self._effect_sequence}",
                self._run_id, f"{self._run_id}:{step.step.step_id}:{self._attempt}",
                now, deadline, effect,
            )
            self._emitted[str(envelope.effect_id)] = str(envelope.action_instance_id)
            envelopes.append(envelope)
        return tuple(envelopes)

    def _finish(self, reason: ExitReason, result: object, error: str | None) -> None:
        step = self._step()
        assert step is not None
        self._results.append(StepResult(step.step.step_id, self._attempt, reason, result, error))
        self._instance = None
        self._pending = None
        self._error = error
        if self._cancel_requested or reason is ExitReason.CANCELLED:
            self._status = RunStatus.CANCELLED
        elif reason is ExitReason.FAILED and self._attempt < step.step.max_attempts:
            self._status = RunStatus.RUNNING
        elif reason is ExitReason.FAILED and step.step.on_failure is FailurePolicy.STOP:
            self._status = RunStatus.FAILED
        else:
            self._index += 1
            self._attempt = 0
            self._status = RunStatus.SUCCEEDED if self._step() is None else RunStatus.RUNNING

    def _exit(self, snapshot, now: TimePoint) -> RunUpdate:
        assert self._instance is not None and self._pending is not None
        reason, result, error = self._pending
        try:
            decision = self._instance.exit(snapshot, reason)
            if not isinstance(decision, ExitDecision):
                raise TypeError("Action exit must return ExitDecision")
            envelopes = self._envelopes(decision.effects, now)
        except Exception as exc:
            self._error = f"exit barrier pending: {exc}"
            return self._view()
        if decision.complete:
            self._finish(reason, result, error)
        return self._view(envelopes)

    def tick(self, now: TimePoint) -> RunUpdate:
        if not isinstance(now, TimePoint):
            raise TypeError("now must be TimePoint")
        if self._status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
            return self._view()
        snapshot = self._world.snapshot()
        if snapshot is None or snapshot.published_at.clock_domain_id != now.clock_domain_id:
            self._error = "world snapshot unavailable or clock domain mismatch"
            return self._view()
        age_ns = now.monotonic_ns - snapshot.published_at.monotonic_ns
        if age_ns < 0 or age_ns > self._max_age_ns:
            self._error = "world snapshot is future or stale"
            return self._view()
        if self._status is RunStatus.EXITING:
            return self._exit(snapshot, now)
        step = self._step()
        assert step is not None
        if self._instance is None:
            self._attempt += 1
            try:
                self._instance = step.registration.factory.start(step.step.parameters, snapshot)
                if not hasattr(self._instance, "tick") or not hasattr(self._instance, "exit"):
                    raise TypeError("Action factory must return an ActionInstance")
            except Exception as exc:
                self._finish(ExitReason.FAILED, None, f"Action start failed: {exc}")
                return self._view()
        try:
            if hasattr(self._instance, "tick_with_results"):
                action_id = f"{self._run_id}:{step.step.step_id}:{self._attempt}"
                results = tuple(result for result in self._effect_results.values()
                                if result.action_instance_id == action_id)
                decision = self._instance.tick_with_results(snapshot, results)
            else:
                decision = self._instance.tick(snapshot)
            if not isinstance(decision, ActionDecision):
                raise TypeError("Action tick must return ActionDecision")
            envelopes = self._envelopes(decision.effects, now)
        except Exception as exc:
            self._pending = (ExitReason.FAILED, None, f"Action tick failed: {exc}")
            self._status = RunStatus.EXITING
            self._error = self._pending[2]
            return self._view()
        self._error = None
        if decision.outcome is ActionOutcome.SUCCEEDED:
            self._pending = (ExitReason.SUCCEEDED, decision.result, None)
            self._status = RunStatus.EXITING
        elif decision.outcome is ActionOutcome.FAILED:
            self._pending = (ExitReason.FAILED, None, decision.error)
            self._status = RunStatus.EXITING
        return self._view(envelopes)
