"""Compatibility import for migrated CUADC field owner."""

import sys as _sys
from importlib import import_module as _import_module

_sys.modules[__name__] = _import_module("applications.cuadc_2026.field_service")
