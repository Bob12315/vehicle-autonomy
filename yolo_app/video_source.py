"""Compatibility import for the Camera sensor implementation."""

import sys as _sys
from importlib import import_module as _import_module

_sys.modules[__name__] = _import_module("sensors.camera.video_source")
