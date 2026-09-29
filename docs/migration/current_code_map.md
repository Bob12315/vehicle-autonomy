# P1-01 当前源码 → V1 架构映射

**状态：P1 历史源码分析，非当前迁移完成清单；证据链接已指向搬迁后的实现。** 依据当前 `main` 分支源码静态读取；未启动服务、SITL 或真机。本文所称“目标归属”是未来 owner，不表示目录已经迁移。冻结边界见[总览](../architecture/overview.md)，阶段顺序见[执行计划](refactor_plan_v1.md)。

## 当前可达的生产入口

```text
app/main.py → SystemRunner(application/runner.py)
  ├→ ServiceManager(app/bootstrap.py)
  │   ├→ YoloUdpReceiver → perception / scene snapshot
  │   └→ LinkManager(telemetry_link) → vehicle state / command adapter
  ├→ MissionApplicationService → MissionOrchestrator / Action Lab
  ├→ ActionRuntimeService → ActionRunner → ActionDispatcher
  ├→ FieldService + FusionManager + ApplicationStateStore
  └→ WebServices → web_ui routers
```

证据：[入口](../../app/main.py#L32)、[SystemRunner 组装](../../application/runner.py#L90)、[服务启动](../../app/bootstrap.py#L287)、[后台任务 tick](../../application/runner.py#L222)。`application/core/` 存在另一个 Core runtime 组装函数，但全仓非测试代码未找到 `build_core_runtime` 调用；它不应被写成当前 `app/main.py` 的 Mission / Action owner，见[组装函数](../../application/core/runtime.py#L38)。

## 模块映射

| 当前路径 | 源码确认的职责 | V1 目标归属 | 判定 |
| --- | --- | --- | --- |
| `app/` | CLI 与 YAML 加载、进程入口；`bootstrap.py` 同时组装 LinkManager、YOLO UDP receiver 与 FusionManager | `app/` composition root、`deployment/`；具体设备 adapter 归相应层 | 保留入口；拆出混在 bootstrap 的传感器/平台实现。证据：[配置](../../app/config.py#L185)、[bootstrap](../../app/bootstrap.py#L24) |
| `application/` | `SystemRunner` 持有 Mission、Action、Field、Web、状态和发送端口；`MissionApplicationService` 管理运行授权；`WebServices` 暴露应用接口 | `application/` Use Case；运行协调逐步进入 `core/runtime/` | 服务和状态门面可保留，`SystemRunner` 是高耦合 owner。证据：[组装](../../application/runner.py#L90)、[Mission Service](../../application/mission_service.py#L18)、[Web facade](../../application/web_services.py#L36) |
| `application/core/` | 已实现 RuntimeInput、run coordinator、scheduler、effect dispatcher 组装，未见生产入口调用 | `core/runtime/`、`core/lifecycle/` 与 Application 适配 | 可作为迁移候选，不能假定已接管生产。证据：[runtime](../../application/core/runtime.py#L27)、[snapshot collector](../../application/core/snapshot_collector.py#L40) |
| `missions/` | `missions/engine.py` 顺序编排、blackboard、retry/branch；`missions/core/` 有编译、catalog 和 legacy Action adapter | `core/mission/`、`core/action/`、`missions/` | 保留已验证的编排概念；生产与候选 Core 分别标注。证据：[orchestrator](../../missions/engine.py#L88)、[production catalog 候选](../../missions/core/production_catalog.py#L50) |
| `missions/common/actions/` | 注册目录混合 takeoff/land、Field 坐标 goto、视觉定位、投放与 CUADC 目标筛选 | 通用 Action + `vehicles/multirotor/actions/` + `applications/cuadc_2026/` | 必须逐 Action 按语义分类，不能整目录移动。证据：[统一 catalog](../../applications/cuadc_2026/actions/definitions.py#L102)、[FIELD goto](../../applications/cuadc_2026/actions/goto_waypoint.py#L15)、[投放评分](../../applications/cuadc_2026/actions/definitions.py#L129) |
| `guidance/` | 路点数学、目标投影与多视角 GPS 融合；部分代码在函数内直接导入 `field` 坐标工具 | `guidance/`、`localization/` 或 Environment Contract 实现 | 纯算法可保留；场地坐标依赖须另界定。证据：[路点数学](../../guidance/waypoint_math.py)、[field 导入](../../guidance/gps_derived_enu_fusion.py#L203) |
| `execution/` | 当前 Action policy、授权、Safety Pipeline、Dispatcher；另有 typed v2 EffectDispatcher / SafetyPolicy | `core/execution/`、`core/safety/` 与车辆专用策略 | 当前链必须保留；不可将两套 dispatcher 同时接成生产 writer。证据：[当前 dispatcher](../../execution/dispatcher.py#L24)、[Safety](../../execution/safety_pipeline.py#L173)、[v2 dispatcher](../../execution/dispatcher_v2.py#L25) |
| `telemetry_link/` | LinkManager 管多 source、MAVLink client、状态解析、CommandBroker、ACK、writer，并提供车辆语义方法；v2 broker 默认实发 | `vehicles/multirotor/` + `protocols/mavlink/` + `infrastructure/transports/` 的兼容 facade | 必须拆分，但最后才删除 facade。证据：[LinkManager](../../telemetry_link/link_manager.py#L328)、[writer 分支](../../telemetry_link/link_manager.py#L150)、[MAVLink client](../../telemetry_link/mavlink_client.py#L15) |
| `fusion/` | 融合感知目标与 Drone/Gimbal State，产生 FusedState | `perception/fusion/`、`world_model/` 的输入转换 | 算法可保留；输出还不是通用 WorldSnapshot。证据：[FusionManager](../../fusion/fusion_manager.py#L7) |
| `field/` | Competition Field Profile、坐标、GPS 参考与校准事务；与命令版本清理联动 | `environments/cuadc_2026/` + `contracts/environment/` | 需保留当前坐标与安全前置条件，逐步抽成 Environment。证据：[FieldService](../../applications/cuadc_2026/field_service.py)、[坐标](../../environments/cuadc_2026/field/coordinates.py)、[版本取消绑定](../../application/runner.py#L137) |
| `yolo_app/` | 同一进程组装 VideoSource、RKNN tracker、目标管理、UDP 发布、MJPEG、录制及视觉控制接收 | `sensors/camera/` + `perception/` + media/Application adapter | 分边界迁移；YOLO/RKNN 是当前具体实现。证据：[main 组装](../../yolo_app/main.py#L50)、[VideoSource](../../sensors/camera/video_source.py#L19)、[RKNN](../../perception/yolo_rknn/rknn_detector.py#L40) |
| `web_ui/` | FastAPI routers、页面、状态与当前 Mission 模板操作；通过 `WebServices` 调用应用服务，但直接构造 `MissionActionStep` | `web_ui/` Application adapter | UI 基础设施可保留，DTO 与 Mission 定义应进一步分离。证据：[router](../../web_ui/routers/missions.py#L5)、[control](../../web_ui/routers/control.py#L9) |
| `contracts/` | 并存旧 Action/Field/State Contract 与 `contracts/core/`、`contracts/platform/`；后者仍含 UAV/Field 专用类型 | V1 `contracts/core/vehicle/sensor/perception/world/...` | 复用成熟类型，按依赖方向整理；不能把现有目录名当作已冻结边界。证据：[Core EffectKind](../../contracts/core/effects.py#L11)、[平台 Port](../../contracts/platform/ports.py#L14) |
| `config/` | app、telemetry、YOLO、Safety、Field Profile 与比赛 Mission JSON；RK3588 real/SITL profiles | 组合式 Deployment / Vehicle / Sensor / Environment / Mission Profile | 当前配置继续保留；未来由 composition root 解析。证据：[当前配置](../../config/app.yaml)、[Mission 模板](../../config/action_missions/rescue_2026_full_auto.json) |
| `tests/` | contracts、unit、integration、JS、SITL 与 fake；含现有 Safety、broker、Mission 等回归资产 | 各层 contract / unit / integration / SITL 长期测试 | 保留并按边界复用。证据：[Safety test](../../tests/unit/execution/test_p0_safety_pipeline.py)、[broker test](../../tests/unit/adapters/test_command_broker.py)、[Web test](../../tests/integration/test_p0_web_security.py) |
| `tools/`、`scripts/` | 独立诊断与验收工具；`tools/telemetry_debug.py` 直接构造 LinkManager 并接受文本控制命令 | 开发/验证工具，须受同等车辆命令出口约束 | 非 `app/main.py` 生产入口，但需要单独审计和隔离。证据：[诊断入口](../../tools/telemetry_debug.py#L22)、[直接命令](../../telemetry_link/command_dispatcher.py#L65) |

## 第一轮可保留与必须拆分

可直接作为迁移资产的是：Action Registry / Runner 的生命周期与已测试行为、Mission 顺序编排、Execution Safety checks、v2 broker 的队列/取消/ACK 机制、Web facade、YOLO 检测实现、Field 坐标与校准算法、现有 fake 与回归测试。“保留”指复用行为与代码资产，不等于保持其现有 owner 和依赖方向。

最需要拆边界的是：`SystemRunner` 的组合与用例职责、`missions/common/actions/` 的通用/车辆/应用混合、`telemetry_link/` 的 Vehicle/MAVLink/Transport 混合、`yolo_app/` 的 Camera/Perception/Media 混合、`field/` 的比赛 Environment 语义，以及旧/新 Core 并存时的生产 owner。具体依赖证据见[审计](dependency_audit.md)，当前控制保护见[安全基线](safety_baseline.md)。
