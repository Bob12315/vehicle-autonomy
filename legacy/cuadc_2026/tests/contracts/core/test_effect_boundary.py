from dataclasses import dataclass
from typing import get_type_hints

from contracts.action import ActionResult
from contracts.core.action import EffectEmission
from contracts.core.common import EffectId, IdempotencyKey, InputSnapshotId
from contracts.core.effects import Takeoff as CoreTakeoff, TypedEffect
from contracts.core.execution import EffectEnvelope
from contracts.core.input_state import InputSnapshotRef
from contracts.effects import Takeoff as ProductionTakeoff
from contracts.platform.common import ActionInstanceId, ResourceVersion, RunExecutionGeneration, RunId
from missions.core.legacy_action_adapter import LegacyActionModuleAdapter


@dataclass(frozen=True, slots=True)
class ExampleDomainEffect:
    kind: str = "example.domain.operation"


def test_canonical_envelope_accepts_typed_domain_payload_without_new_envelope() -> None:
    assert get_type_hints(EffectEnvelope)["effect"] is TypedEffect
    assert get_type_hints(EffectEmission)["effect"] is TypedEffect
    payload = ExampleDomainEffect()
    ref = InputSnapshotRef(InputSnapshotId("input-1"), ResourceVersion("input", 1))
    envelope = EffectEnvelope(
        EffectId("effect-1"), IdempotencyKey("effect-1"), RunId("run-1"),
        RunExecutionGeneration(2), ActionInstanceId("action-1"), 3,
        "local-1", payload, ref,
    )
    assert envelope.effect is payload
    assert envelope.emitted_input_ref is ref
    assert envelope.run_execution_generation == 2


def test_existing_legacy_adapter_converts_production_result_into_typed_emission() -> None:
    result = ActionResult(effects=[ProductionTakeoff(params={"altitude_m": 4.0})])
    adapter = LegacyActionModuleAdapter(lambda: object(), "takeoff")
    emissions = adapter._effects(result.effects)
    assert len(emissions) == 1
    assert isinstance(emissions[0].effect, CoreTakeoff)
    assert emissions[0].effect.altitude_m == 4.0
    assert emissions[0].local_token == "legacy:takeoff:1"
