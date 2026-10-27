"""Non-authorizing proof that the pinned native zero traversed the data path.

Cold encrypted delivery may be delayed and CollisionMonitor suppresses repeated
stopped zeros. These observations are NEVER controller freshness evidence,
NavigationCommands, vehicle-state evidence, or permission to move.
"""
from collections import OrderedDict
import math


class PreparationChannelEvidence:
    CAPACITY = 16

    def __init__(self, raw_gid, final_gid):
        if any(not isinstance(gid,str) or len(gid) not in (32,48)
               or any(c not in '0123456789abcdef' for c in gid)
               or set(gid)=={'0'} for gid in (raw_gid,final_gid)):
            raise ValueError('actual pinned native publishers required')
        self.gids={'raw':raw_gid,'final':final_gid}
        self.samples={'raw':OrderedDict(),'final':OrderedDict()}

    def observe(self, channel, gid, source_stamp_ns, values, received_ns):
        if channel not in self.gids or gid!=self.gids[channel]:
            raise ValueError('preparation publisher mismatch')
        if any(type(v) is not int or v<0 for v in (source_stamp_ns,received_ns)):
            raise ValueError('original preparation metadata required')
        if (not isinstance(values,tuple) or len(values)!=6
                or any(type(v) not in (int,float) or not math.isfinite(v) or v!=0 for v in values)):
            raise ValueError('preparation data path requires full actual zero')
        records=self.samples[channel]
        if source_stamp_ns not in records:records[source_stamp_ns]=received_ns
        while len(records)>self.CAPACITY:records.popitem(last=False)

    def proof(self):
        common=self.samples['raw'].keys() & self.samples['final'].keys()
        if not common:return None
        stamp=max(common)
        return dict(source_stamp_ns=stamp,raw_gid=self.gids['raw'],final_gid=self.gids['final'],
                    raw_received_ns=self.samples['raw'][stamp],final_received_ns=self.samples['final'][stamp],
                    control_eligible=False)
