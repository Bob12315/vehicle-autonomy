from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def imported_roots(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            result.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            result.add(node.module.split(".", 1)[0])
    return result


@pytest.mark.parametrize("directory,forbidden", [
    ("contracts/sensors", {"cv2", "numpy", "yolo_app", "telemetry_link", "socket", "serial"}),
    ("world_model", {"cv2", "numpy", "yolo_app", "telemetry_link", "socket", "serial",
                     "pymavlink", "execution", "missions", "app"}),
    ("yolo_app", {"pymavlink", "telemetry_link", "execution"}),
])
def test_sensor_perception_world_import_boundaries(directory: str, forbidden: set[str]) -> None:
    violations = [f"{path.relative_to(ROOT)}: {name}"
                  for path in (ROOT / directory).rglob("*.py")
                  for name in imported_roots(path) & forbidden]
    assert not violations, "\n".join(violations)
