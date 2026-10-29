"""Evidence comparison. Missing measurements never become passing samples."""
from __future__ import annotations

import math

STATUSES = frozenset({'PASS', 'FAIL', 'BLOCKED', 'NOT_TESTED'})
LEVELS = tuple(f'L{i}' for i in range(1, 7))


def compare_reports(baseline: dict, candidate: dict, *, relative_tolerance: float = .2) -> dict:
    """Compare matching scene/vehicle reports and measured numeric metrics only.

    This is a diagnostic difference, not an automatic promotion of acceptance
    levels. A faster world-only run does not establish vehicle readiness.
    """
    if type(relative_tolerance) not in (int, float) or not math.isfinite(relative_tolerance) or not 0 <= relative_tolerance <= 10:
        raise ValueError('finite relative tolerance in [0,10] required')
    identity = ('scene_id', 'vehicle')
    mismatches = [key for key in identity if baseline.get(key) != candidate.get(key)]
    left_seed = baseline.get('configuration', {}).get('seed', baseline.get('seed'))
    right_seed = candidate.get('configuration', {}).get('seed', candidate.get('seed'))
    if left_seed != right_seed: mismatches.append('seed')
    if baseline.get('configuration', {}).get('parameters') != candidate.get('configuration', {}).get('parameters'): mismatches.append('parameters')
    if mismatches:
        raise ValueError('reports have different configuration: ' + ', '.join(mismatches))
    levels = []
    for key in LEVELS:
        before = baseline.get('levels', {}).get(key, 'NOT_TESTED')
        after = candidate.get('levels', {}).get(key, 'NOT_TESTED')
        if isinstance(before, dict): before = before.get('status', 'NOT_TESTED')
        if isinstance(after, dict): after = after.get('status', 'NOT_TESTED')
        if before not in STATUSES or after not in STATUSES:
            raise ValueError('invalid acceptance status')
        levels.append(dict(level=key, baseline=before, candidate=after,
                           regression=before == 'PASS' and after != 'PASS'))
    metrics = []
    # Lower resource use/loading time is favorable; RTF is higher-is-better.
    for key, higher in [('rtf', True), ('load_seconds', False), ('cpu_percent', False), ('rss_mib', False)]:
        left = baseline.get('metrics', {}).get(key)
        right = candidate.get('metrics', {}).get(key)
        available = all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in (left, right))
        fraction = (right - left) / left if available and left else None
        regression = None if fraction is None else (fraction < -relative_tolerance if higher else fraction > relative_tolerance)
        metrics.append(dict(metric=key, baseline=left, candidate=right, relative_change=fraction,
                            regression=regression, status='PASS' if available else 'NOT_TESTED'))
    return dict(configuration=dict(scene_id=candidate.get('scene_id'), vehicle=candidate.get('vehicle'), seed=right_seed), levels=levels, metrics=metrics,
                has_regression=any(item['regression'] is True for item in levels + metrics),
                note='Measured diagnostics only; different host load can affect performance.')
