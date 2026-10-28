"""Read-only Phase 4 queries and bounded deterministic event input.

No sensor fusion, coordinate conversion or authentication promotion occurs here.
"""
from dataclasses import dataclass
from datetime import datetime
from vehicle_autonomy.contracts.core.time import TimePoint
from threading import RLock
from vehicle_autonomy.contracts.core.primitives import thaw_json
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.mission import BlackboardValue, Truth


@dataclass(frozen=True)
class MissionEvent:
    sequence: int
    id: str
    name: str
    data: BlackboardValue


class LocalEvents:
    def __init__(self, limit=1024):
        if type(limit) is not int or not 1 <= limit <= 4096: raise ValueError('event budget required')
        self.limit = limit
        self._events = []
        self._ids = set()
        self._lock = RLock()

    @property
    def cursor(self):
        with self._lock: return len(self._events)

    def publish(self, identifier, name, value, now, *, ttl_s=5, quality='VALID', frame=None):
        if not all(isinstance(s, str) and 0 < len(s) <= 128 for s in (identifier, name)):
            raise ValueError('bounded event identity required')
        if type(ttl_s) not in (int, float) or not 0 < ttl_s <= 60: raise ValueError('bounded event TTL required')
        with self._lock:
            if identifier in self._ids: return False
            if len(self._events) >= self.limit: raise ValueError('event budget exhausted; epoch renewal required')
            data = BlackboardValue(value, now, int(ttl_s * 1e9), quality, frame, 'explicit-event-source')
            self._events.append(MissionEvent(len(self._events) + 1, identifier, name, data))
            self._ids.add(identifier)
            return True

    def read(self, after, name, now):
        with self._lock:
            return tuple(e for e in self._events if e.sequence > after and e.name == name and usable(e.data, now))


def usable(value, now, *, frame=None, max_age_s=None):
    if not isinstance(value, BlackboardValue) or value.quality != 'VALID': return False
    try: age = now.elapsed_ns_since(value.observed_at)
    except ValueError: return False
    bound = value.valid_for_ns if max_age_s is None else min(value.valid_for_ns, int(max_age_s * 1e9))
    return 0 <= age < bound and (frame is None or value.frame == frame)


def query(world, path):
    if world is None or not isinstance(path, str): return None
    stamp = world.published_at
    frame = None
    quality = 'VALID'
    current = world
    for part in path.split('.'):
        if part.startswith('_'): return None
        if isinstance(current, dict): current = current.get(part)
        else: current = getattr(current, part, None)
        if current is None: return None
        if hasattr(current, 'captured_at'): stamp = current.captured_at
        elif hasattr(current, 'published_at'): stamp = current.published_at
        if hasattr(current, 'frame_id'): frame = str(current.frame_id)
        if hasattr(current, 'quality'):
            q = current.quality
            quality = q.value if hasattr(q, 'value') else q
        if hasattr(current, 'health') and current.health.quality.value != 'VALID': quality = 'UNKNOWN'
    try: value = to_json_value(current)
    except (ValueError, TypeError): return None
    return BlackboardValue(value, stamp, 3_000_000_000, quality, frame, 'world:' + path)


def evaluate(expression, world, blackboard, now, *, resolver=None):
    op = expression['op']
    if op in ('all', 'any'):
        values = [evaluate(e, world, blackboard, now,resolver=resolver) for e in expression['args']]
        if op == 'all':
            return Truth.FALSE if Truth.FALSE in values else Truth.UNKNOWN if Truth.UNKNOWN in values else Truth.TRUE
        return Truth.TRUE if Truth.TRUE in values else Truth.UNKNOWN if Truth.UNKNOWN in values else Truth.FALSE
    if op == 'not':
        value = evaluate(expression['arg'], world, blackboard, now,resolver=resolver)
        return {Truth.TRUE: Truth.FALSE, Truth.FALSE: Truth.TRUE, Truth.UNKNOWN: Truth.UNKNOWN}[value]
    value = resolver(expression) if resolver else (query(world, expression['path']) if expression['source'] == 'world' else blackboard_query(blackboard, expression['path']))
    if not usable(value, now, frame=expression.get('frame'), max_age_s=expression.get('max_age_s', 3)):
        return Truth.UNKNOWN
    actual, expected = thaw_json(value.value), expression['value']
    same = type(actual) is type(expected) or type(actual) in (int, float) and type(expected) in (int, float)
    if not same or type(actual) not in (bool, str, int, float, type(None)): return Truth.UNKNOWN
    if op not in ('eq', 'ne') and type(actual) not in (int, float): return Truth.UNKNOWN
    operations = {'eq': lambda: actual == expected, 'ne': lambda: actual != expected,
                  'lt': lambda: actual < expected, 'le': lambda: actual <= expected,
                  'gt': lambda: actual > expected, 'ge': lambda: actual >= expected}
    return Truth.TRUE if operations[op]() else Truth.FALSE


def blackboard_query(blackboard, path):
    root, *parts = path.split('.')
    item = blackboard.get(root)
    if item is None: return None
    value = thaw_json(item.value)
    stamp, quality, frame = item.observed_at, item.quality, item.frame
    def provenance(current):
        nonlocal stamp, quality, frame
        if type(current) is not dict: return
        source = current.get('captured_at', current.get('published_at'))
        if source is not None:
            try:
                original = TimePoint(source['monotonic_ns'],datetime.fromisoformat(source['utc']),source['clock_domain_id'])
                delta = stamp.elapsed_ns_since(original)
                if delta < 0: quality = 'UNKNOWN'
                else: stamp = original
            except (TypeError,KeyError,ValueError): quality = 'UNKNOWN'
        if 'frame_id' in current: frame = current['frame_id']
        health = current.get('health')
        q = current.get('quality', health.get('quality') if type(health) is dict else None)
        if q is not None and q != 'VALID': quality = 'UNKNOWN'
    provenance(value)
    for part in parts:
        if type(value) is list and part.isdecimal() and int(part)<len(value):value=value[int(part)]
        elif type(value) is dict and part in value:value=value[part]
        else:return None
        provenance(value)
    return BlackboardValue(value, stamp, item.valid_for_ns, quality, frame, item.source)


def resolve_parameters(parameters, world, blackboard, now):
    result = {}
    for name, value in parameters.items():
        if type(value) is dict and '$query' in value:
            q = value['$query']
            item = query(world, q['path']) if q['source'] == 'world' else blackboard_query(blackboard, q['path'])
            if not usable(item, now, frame=q.get('frame'), max_age_s=q.get('max_age_s', 3)):
                raise ValueError('UNKNOWN parameter observation: ' + name)
            value = thaw_json(item.value)
            if 'offset' in q:
                if type(value) not in (float, int): raise ValueError('numeric observation required')
                value += q['offset']
        result[name] = value
    return result
