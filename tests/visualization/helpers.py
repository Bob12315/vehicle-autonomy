from dataclasses import replace
from vehicle_autonomy.contracts.core.geometry import GeoPoint
from vehicle_autonomy.contracts.core.stamped import Stamped


def gps(h):
    for driver in h.drivers.values():
        original=driver.snapshot
        def snapshot(original=original):
            world=original();v=world.vehicle
            return replace(world,vehicle=replace(v,global_position=Stamped('earth',v.published_at,GeoPoint(-35.,149.,584.))))
        driver.snapshot=snapshot


def sample(kind='rover'):
    return dict(schema=1,target=kind,kind=kind,environment='simulation',epoch='origin:session',origin=dict(id='origin:session',frame='odom',axes='ENU',body='FLU'),
        valid=True,reason=None,age_s=.01,sample_ns='1000000000',pose=dict(position=dict(x=1.,y=2.,z=3.),orientation=dict(x=0.,y=0.,z=0.,w=1.)),
        twist=dict(linear=dict(x=1.,y=0.,z=0.),angular=dict(x=0.,y=0.,z=.1)),twist_frame='odom',gps=None)
