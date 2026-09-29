"""Inventory of existing CUADC assets; no Mission or Action parameters move here."""

from applications.profile import ApplicationProfile, MissionTemplateRef


CUADC_2026_PROFILE = ApplicationProfile(
    profile_id="cuadc_2026",
    deployment_profile_id="onboard_rk3588",
    vehicle_type="multirotor",
    protocol_id="mavlink",
    transport_options=("udp", "serial"),
    sensor_profile_id="usb_camera",
    perception_profile_id="yolo_rknn",
    environment_profile_id="cuadc_2026",
    mission_templates=(
        MissionTemplateRef("drop_two_targets", "投放任务 v2",
                           "config/action_missions/drop_two_targets.json"),
        MissionTemplateRef("recon_gps", "GPS 侦察任务 v2",
                           "config/action_missions/recon_gps.json"),
        MissionTemplateRef("rescue_2026_full_auto", "完整流程 v2",
                           "config/action_missions/rescue_2026_full_auto.json"),
    ),
    action_names=frozenset({
        "goto_waypoint", "target_lock", "align_descend", "payload_release",
        "select_drop_targets", "gps_capture_view", "gps_fuse_views", "gps_target_lock",
    }),
    legacy_config_paths=(
        "config/field_profiles/competition_runtime.json",
        "config/yolo.yaml",
    ),
)
