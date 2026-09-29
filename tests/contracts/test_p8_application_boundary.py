"""CUADC composition is explicit while generic application contracts stay reusable."""

from pathlib import Path

import pytest

from applications import ApplicationCatalog, MissionTemplateRef
from applications.cuadc_2026 import CUADC_2026_PROFILE
from applications.cuadc_2026.composition import compose_actions
from deployment import DeploymentCatalog
from environments.cuadc_2026.adapter import CUADC_PROFILE
from scripts.validate_action_missions import DEFAULT_TEMPLATE_PATHS
from vehicles.multirotor.plugin import MultirotorPlugin
from web_ui.templates import ACTION_MISSION_TEMPLATE_NAMES, load_action_mission_template


ROOT = Path(__file__).resolve().parents[2]


def test_cuadc_application_profile_maps_existing_components() -> None:
    profile = ApplicationCatalog((CUADC_2026_PROFILE,)).get("cuadc_2026")
    assert DeploymentCatalog().require_available(profile.deployment_profile_id).profile_id == "onboard_rk3588"
    assert profile.environment_profile_id == CUADC_PROFILE.profile_id
    assert profile.vehicle_type == "multirotor"
    assert profile.protocol_id == "mavlink"
    assert profile.transport_options == ("udp", "serial")
    assert profile.sensor_profile_id == "usb_camera"
    assert profile.perception_profile_id == "yolo_rknn"
    registered = {action.name for action in compose_actions(MultirotorPlugin())}
    assert profile.action_names <= registered


def test_web_and_validator_share_application_template_inventory() -> None:
    profile = CUADC_2026_PROFILE
    assert tuple(DEFAULT_TEMPLATE_PATHS) == tuple(
        profile.template_path(item.name, ROOT) for item in profile.mission_templates)
    assert ACTION_MISSION_TEMPLATE_NAMES == {
        item.name: item.label for item in profile.mission_templates}
    for item in profile.mission_templates:
        assert profile.template_path(item.name, ROOT).is_file()
        assert load_action_mission_template(item.name)["version"] == 2


def test_generic_profile_rejects_unknown_or_unsafe_template_names() -> None:
    with pytest.raises(KeyError):
        CUADC_2026_PROFILE.template("unknown")
    with pytest.raises(ValueError, match="invalid Mission template"):
        MissionTemplateRef("escape", "Escape", "../outside.json")
    with pytest.raises(ValueError, match="duplicate Mission"):
        from dataclasses import replace
        replace(CUADC_2026_PROFILE, mission_templates=(
            CUADC_2026_PROFILE.mission_templates[0],
            CUADC_2026_PROFILE.mission_templates[0],
        ))


def test_core_has_no_cuadc_application_terms_or_imports() -> None:
    forbidden = ("cuadc", "rescue_2026", "bucket", "drop_zone", "recon_area")
    for folder in ("contracts/core", "missions/core", "application/core"):
        for path in (ROOT / folder).rglob("*.py"):
            source = path.read_text(encoding="utf-8").lower()
            assert not any(term in source for term in forbidden), path
