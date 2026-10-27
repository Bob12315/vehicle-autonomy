"""Algorithm capability metadata, distinct from the security ProviderRegistry."""
from dataclasses import dataclass
from vehicle_autonomy.contracts.action import ActionResource,ResourceMode
from vehicle_autonomy.contracts.streams import identity


@dataclass(frozen=True,slots=True)
class AlgorithmProvider:
    provider_id: str
    provider_type: str
    implementation: str
    version: str
    vehicle_types: frozenset[str]
    capabilities: frozenset[str]
    requirements: frozenset[str]
    outputs: frozenset[str]
    native_interface: str
    profile: str
    resources: tuple[ActionResource,...]
    requires_motion_bridge: bool=False

    def __post_init__(self):
        for v,n in ((self.provider_id,'provider'),(self.implementation,'implementation'),(self.version,'version'),
                    (self.native_interface,'native interface'),(self.profile,'profile')):identity(v,n)
        if self.provider_type not in ('navigation','mapping','vision'):raise ValueError('unknown algorithm provider type')
        if not isinstance(self.vehicle_types,frozenset) or not self.vehicle_types or not self.vehicle_types<={'rover','copter','plane'}:raise ValueError('explicit vehicles required')
        for name in ('capabilities','requirements','outputs'):
            values=getattr(self,name)
            if not isinstance(values,frozenset) or not values or len(values)>64:raise ValueError('bounded immutable '+name+' required')
            for v in values:identity(v,name)
        if not isinstance(self.resources,tuple) or not all(isinstance(r,ActionResource) for r in self.resources):raise TypeError('typed resources required')
        if type(self.requires_motion_bridge) is not bool:raise TypeError('explicit bridge requirement required')


# Shared conflict domain for a native navigation macro; not vehicle authority.
NATIVE_NAVIGATION_RESOURCES=(ActionResource('vehicle.motion',ResourceMode.EXCLUSIVE,'vehicle.control'),ActionResource('navigation.native'))
