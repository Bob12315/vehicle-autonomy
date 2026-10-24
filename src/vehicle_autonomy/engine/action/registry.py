"""Explicit Action registration; there is no global application catalog."""

from __future__ import annotations

from dataclasses import dataclass

from vehicle_autonomy.contracts.decision import ActionFactory, ActionSpec
from vehicle_autonomy.contracts.core.models import ActionDefinition
from vehicle_autonomy.contracts.core.ports import Action
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.engine.action.schema import parameter_schema, decode_parameters


@dataclass(frozen=True)
class RegisteredAction:
    definition: ActionDefinition
    implementation: Action


@dataclass(frozen=True)
class RegisteredTypedAction:
    spec: ActionSpec
    factory: ActionFactory


class ActionRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, RegisteredAction] = {}
        self._typed_entries: dict[str, RegisteredTypedAction] = {}
        self._versions: dict[tuple[str,str],RegisteredTypedAction] = {}

    def register(self, definition: ActionDefinition, implementation: Action) -> None:
        if not definition.name or definition.name in self._entries or definition.name in self._typed_entries:
            raise ValueError(f"Action name is empty or already registered: {definition.name!r}")
        self._entries[definition.name] = RegisteredAction(definition, implementation)

    def register_typed(self, spec: ActionSpec, factory: ActionFactory) -> None:
        if not isinstance(spec,ActionSpec) or not callable(getattr(factory,'start',None)):
            raise TypeError('typed Action specification and factory required')
        if spec.name in self._entries or (spec.name,spec.version) in self._versions:
            raise ValueError(f"Action name is already registered: {spec.name!r}")
        entry=RegisteredTypedAction(spec,factory)
        self._versions[spec.name,spec.version]=entry
        current=self._typed_entries.get(spec.name)
        if current is None or self._version(spec.version)>self._version(current.spec.version):
            self._typed_entries[spec.name]=entry

    @staticmethod
    def _version(value):return tuple(int(v) for v in value.split('.'))

    def resolve(self, name: str) -> RegisteredAction:
        try:
            return self._entries[name]
        except KeyError as exc:
            raise ValueError(f"Action is not registered: {name}") from exc

    def resolve_typed(self, name: str, version: str | None = None) -> RegisteredTypedAction:
        try:
            return self._typed_entries[name] if version is None else self._versions[name,version]
        except KeyError as exc:
            raise ValueError(f"Typed Action is not registered: {name}") from exc

    def metadata(self,name,version=None,*,vehicle_kind=None):
        entry=self.resolve_typed(name,version);s=entry.spec
        schema=parameter_schema(s.parameters_type)
        overrides=to_json_value(s.vehicle_parameter_overrides) or {}
        times=(to_json_value(s.vehicle_timeout_overrides) or {}).get(vehicle_kind,{})
        for field,updates in overrides.get(vehicle_kind,{}).items():
            if field not in schema['properties']:raise ValueError('override for unknown Action parameter')
            schema['properties'][field].update(updates)
        return dict(name=s.name,version=s.version,description=s.description,kind=s.kind.value,
            parameters=schema,output=to_json_value(s.output_schema),vehicle_types=sorted(s.vehicle_types),
            required_capabilities=sorted(s.required_capabilities),required_state=list(s.required_state),
            resources=[dict(name=r.name,mode=r.mode.value,conflict_group=r.conflict_group) for r in s.resources],
            default_timeout_s=times.get('default_timeout_ns',s.default_timeout_ns)/1e9,
            max_timeout_s=times.get('max_timeout_ns',s.max_timeout_ns)/1e9,
            max_snapshot_age_s=s.max_snapshot_age_ns/1e9,exit_timeout_s=s.exit_timeout_ns/1e9,
            effect_ttl_s=s.effect_ttl_ns/1e9,effect_ttl_overrides_s={k:v/1e9 for k,v in (to_json_value(s.effect_ttl_overrides) or {}).items()},
            implementation=s.implementation_ref or type(entry.factory).__module__+'.'+type(entry.factory).__qualname__,
            success_semantics=s.success_semantics,cancel_semantics=s.cancel_semantics)

    def catalog(self,*,vehicle_kind=None,capabilities=None):
        result=[]
        for (name,version),entry in sorted(self._versions.items()):
            s=entry.spec
            if vehicle_kind is not None and s.vehicle_types and vehicle_kind not in s.vehicle_types:continue
            if capabilities is not None and not s.required_capabilities<=frozenset(capabilities):continue
            result.append(self.metadata(name,version,vehicle_kind=vehicle_kind))
        return result

    def parameters(self,name,values,version=None,*,vehicle_kind=None):
        entry=self.resolve_typed(name,version)
        result=decode_parameters(entry.spec.parameters_type,values,self.metadata(name,version,vehicle_kind=vehicle_kind)['parameters'])
        entry.spec.validate_parameters(result)
        return result
