# V1 目标目录结构

**状态：Frozen Target Architecture。** 以下是后续迁移的目标组织方式，**不表示当前仓库已创建或实现这些目录**。本轮不为目标结构预建空 Python package。当前实际目录见[当前状态](../migration/current_state.md)。

```text
vehicle-autonomy-framework/
├── app/
├── application/
├── core/
│   ├── runtime/
│   ├── mission/
│   ├── action/
│   ├── execution/
│   ├── safety/
│   └── lifecycle/
├── contracts/
│   ├── core/
│   ├── vehicle/
│   ├── sensor/
│   ├── perception/
│   ├── world/
│   ├── planning/
│   ├── environment/
│   └── intelligence/
├── vehicles/
│   ├── multirotor/
│   ├── rover/
│   ├── fixed_wing/
│   ├── vtol/
│   └── future_vehicle/
├── sensors/
│   ├── camera/
│   ├── lidar/
│   ├── radar/
│   ├── gps/
│   ├── imu/
│   ├── depth_camera/
│   └── future/
├── perception/
│   ├── detection/
│   ├── tracking/
│   ├── segmentation/
│   ├── depth/
│   ├── obstacle/
│   ├── fusion/
│   └── future/
├── localization/
│   ├── gps/
│   ├── vio/
│   ├── lidar_slam/
│   ├── fusion/
│   ├── state_estimation/
│   └── future/
├── mapping/
│   ├── occupancy/
│   ├── pointcloud/
│   ├── semantic/
│   ├── terrain/
│   └── future/
├── world_model/
├── planning/
├── guidance/
├── intelligence/
│   ├── llm/
│   ├── vlm/
│   ├── policy/
│   ├── agent/
│   └── mission_planner/
├── environments/
├── applications/
│   └── cuadc_2026/
├── missions/
├── protocols/
│   ├── mavlink/
│   └── future/
├── infrastructure/
│   └── transports/
│       ├── serial/
│       ├── udp/
│       ├── tcp/
│       └── future/
├── gateway/
├── deployment/
├── web_ui/
├── config/
├── runtime/
└── tests/
```

Camera 是 Sensor，视频是 CameraFrame 数据流；不建立与 `sensors/` 平级的 `video/` 一级模块。目录只表达边界和依赖方向；每个具体实现须在后续迁移中单独评估与验证。
