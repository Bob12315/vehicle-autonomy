"""Compatibility import for the RKNN Perception implementation."""

import sys as _sys
from importlib import import_module as _import_module

_sys.modules[__name__] = _import_module("perception.yolo_rknn.target_manager")
