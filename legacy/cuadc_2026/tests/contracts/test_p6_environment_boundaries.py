"""Keep the new framework environment boundary free of CUADC implementation imports."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_generic_environment_modules_do_not_import_field_or_application() -> None:
    paths = [ROOT / "contracts" / "environment" / "model.py",
             ROOT / "environments" / "catalog.py"]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [node.module for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom) and node.module]
        assert all(not name.startswith(("field", "application", "environments.cuadc_2026"))
                   for name in imports), path
