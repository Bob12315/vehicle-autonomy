"""Read-only access to the versioned, bounded release audit."""
import json
from pathlib import Path


def release_audit(root):
    root=Path(root)
    path=root/'docs/HARDWARE_READY_AUDIT.md'
    if not path.is_file() or path.stat().st_size>100_000:
        raise ValueError('versioned hardware-ready audit is not available')
    marker=root/'.source-version.json'
    source=None
    if marker.is_file() and marker.stat().st_size<65536:
        source=json.loads(marker.read_text()).get('source_commit')
    return {'kind':'versioned release audit','source_commit':source,'text':path.read_text(),
            'physical_acceptance':'BLOCKED; this document is not permission to move a real vehicle'}
