"""Locate versioned resources in a source checkout or installed release."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def resource_root() -> Path:
    """Resolve resources without depending on the caller's working directory.

    An explicit root is useful for an offline deployment with external resources.
    Invalid explicit roots fail rather than silently selecting another release.
    """
    configured = os.environ.get('VAF_RESOURCE_ROOT')
    if configured:
        root = Path(configured).expanduser().resolve()
        if not all((root / name).is_dir() for name in ('configs', 'simulation', 'scripts', 'docs')):
            raise ValueError('VAF_RESOURCE_ROOT must contain configs, simulation, scripts and docs')
        return root
    package = Path(__file__).resolve().parent
    root = package.parent.parent
    if (package.parent.name == 'src' and (root / 'pyproject.toml').is_file()
            and (root / 'simulation').is_dir() and (root / 'configs').is_dir()):
        return root
    root = Path(sys.prefix) / 'share' / 'vehicle-autonomy'
    if all((root / name).is_dir() for name in ('configs', 'simulation', 'scripts', 'docs')):
        return root
    raise FileNotFoundError('Vehicle Autonomy resources missing; install the package or set VAF_RESOURCE_ROOT')
