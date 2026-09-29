"""Adding Rover must not add vehicle imports or branches to generic layers."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_generic_layers_do_not_import_fake_rover() -> None:
    for directory in ("contracts/core", "application/core", "missions/core",
                      "world_model", "protocols"):
        for path in (ROOT / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = [node.module for node in ast.walk(tree)
                       if isinstance(node, ast.ImportFrom) and node.module]
            assert all(not module.startswith("vehicles.rover") for module in imports), path
