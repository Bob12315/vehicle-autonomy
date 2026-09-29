"""P2-01 guard for the existing Core contract import boundary."""

import ast
from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[3] / "contracts" / "core"
REPO_ROOT = CORE_ROOT.parents[1]
FORBIDDEN_ROOTS = {
    "app", "application", "execution", "field", "fusion", "missions", "perception", "sensors",
    "telemetry_link", "vehicles", "web_ui", "yolo_app", "pymavlink",
    "fastapi", "rknnlite", "rknn", "serial", "socket",
}


def test_core_contracts_do_not_import_implementations_or_hardware() -> None:
    violations = []
    for path in CORE_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = (node.module,)
            else:
                continue
            for module in modules:
                if module.split(".", 1)[0].lower() in FORBIDDEN_ROOTS:
                    violations.append(f"{path.name}:{node.lineno}: {module}")
    assert not violations, "Core contract import violations: " + ", ".join(violations)


def test_effect_payload_contract_does_not_gain_new_domain_imports() -> None:
    path = CORE_ROOT / "effects.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0
        and node.module and node.module.startswith("contracts.")
    }
    # Existing Field version dependency is compatibility debt for P6.
    assert imports <= {"contracts.platform.field"}


def test_core_runtime_and_mission_modules_do_not_import_hardware_or_vehicles() -> None:
    roots = (
        REPO_ROOT / "contracts" / "core",
        REPO_ROOT / "application" / "core",
        REPO_ROOT / "missions" / "core",
    )
    forbidden = {"pymavlink", "serial", "socket", "rknn", "rknnlite", "fastapi", "vehicles"}
    violations = []
    for root in roots:
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = (alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = (node.module,)
                else:
                    continue
                for module in modules:
                    if module.split(".", 1)[0].lower() in forbidden:
                        violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {module}")
    assert not violations, "Core hardware/vehicle import violations: " + ", ".join(violations)
