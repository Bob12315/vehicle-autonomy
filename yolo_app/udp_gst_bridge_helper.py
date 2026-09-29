"""Compatibility import for the Camera sensor implementation."""

import sys as _sys
from importlib import import_module as _import_module

if __name__ == "__main__":
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

_sys.modules[__name__] = _import_module("sensors.camera.udp_gst_bridge_helper")

if __name__ == "__main__":
    raise SystemExit(_sys.modules[__name__].main())
