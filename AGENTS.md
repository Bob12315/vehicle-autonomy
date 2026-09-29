# AI Development Entry

本仓库以 **Vehicle Autonomy Framework V1 Frozen Target Architecture** 作为后续修改的架构依据。文档描述目标；当前源码仍主要是 CUADC 2026 多旋翼实现。不得把目标目录、接口或控制链误称为已落地。

## 修改前必读

1. `README.md`
2. `docs/README.md`
3. `docs/architecture/overview.md`
4. `docs/architecture/principles.md`
5. `docs/architecture/dependency_rules.md`
6. `docs/migration/current_state.md`
7. `docs/migration/refactor_plan_v1.md`（执行迁移任务时）

修改前先判断功能属于哪个架构层，再查看对应专题文档和实际源码、配置、测试。目标架构决定新的依赖方向；当前运行事实必须从源码核对。

## 架构红线

1. 任何车辆运动都不能绕过 Execution、Authorization、Safety；Safety 有最终裁决权。
2. AI、Mission、Web、Perception 和 Planner 都不能直接获得 `VehicleCommandPort` 或底层协议/设备发送能力。
3. 车辆专用能力与逻辑留在 Vehicle Plugin / Contract，不把 `vehicle_type` 分支放进通用 Core。
4. Mission 只编排已注册 Action，不直接操作 Protocol、Transport 或硬件。
5. 不创建第二套控制链；协议与传输保持分离。
6. 不把 V1 target architecture 当作 current implementation。
7. 部署位置与 Environment Profile 不改变业务层的权限边界。

## 当前实现保护

本仓库当前 Action Mission 与 Web UI 路径、`ActionRuntimeService → ActionDispatcher → ActionSafetyPipeline → LinkManager → telemetry_link` 发送路径仍在使用。后续迁移必须先核对实际调用和测试，不得依据目标图直接删除当前实现。保持 `executor.send_commands: false` 默认值、系统 SEND 与 Action 授权双门控、连续命令退出时的显式 stop/zero 与旧命令清理。当前 `payload_release` 只经 `set_servo`；`yolo_app/` 不直接连接 MAVLink 或产生飞行命令。

P1 分析结果见[源码映射](docs/migration/current_code_map.md)、[依赖审计](docs/migration/dependency_audit.md)和[安全基线](docs/migration/safety_baseline.md)。执行任务须遵守[阶段计划](docs/migration/refactor_plan_v1.md)与[迁移原则](docs/migration/migration_principles.md)。每完成一个已获用户授权的阶段，验证后提交 Git。
