# P2 / P3 验收记录

## P2：Contract 与 Runtime Input

| 子项 | 当前实现 | 验证 |
| --- | --- | --- |
| P2-01 Core Types | 复用 `contracts.platform.common` 的 Run / Action / Lease 身份；`contracts.core.common` 增加深度不可变 JSON 校验 | `tests/contracts/core/test_common_contracts.py` |
| P2-02 Typed Effect | `contracts.core.effects.TypedEffect`、既有 EffectEnvelope 和效果状态投影；Action 与执行副作用分离 | `tests/contracts/core/test_effect_boundary.py`、`tests/unit/core/test_effect_status_projection.py` |
| P2-03 Runtime Input | `RuntimeInputSnapshot` 是单次采集、版本化、不可变的周期输入；车辆、感知、Field、Fusion、SEND 统一发布。预留深度不可变的 World / System / Run 投影；跨时钟域与未来时间戳标记 INVALID | `tests/unit/core/test_runtime_input_boundary.py` |
| P2-04 静态依赖 | AST 测试禁止 `contracts/core`、`application/core`、`missions/core` 直接引入硬件库、FastAPI 或具体 Vehicle | `tests/contracts/core/test_dependency_boundary.py` |

当前生产 Action 使用构建好的运行上下文；候选 Core 的 Action Tick 使用 `RuntimeInputSnapshot`。World / System / Run 投影尚无独立上游 producer，不能声称完整 World Model 已落地。`contracts/core/input_state.py` 与 `contracts/core/effects.py` 仍复用旧平台 Field/Vehicle DTO，这是 P5/P6 进一步去领域化的依赖，不允许借本阶段引入第二套不兼容消息。

## P3：Vehicle Plugin

| 子项 | 当前实现 |
| --- | --- |
| P3-01 Contract | `contracts/vehicle/` 定义 VehicleCapabilities、VehicleHealth、VehiclePlugin；VehicleStatePort / VehicleCommandPort 复用既有纯 DTO 端口 |
| P3-02 Multirotor | `vehicles/multirotor/` 提供能力声明、健康映射、起飞/降落/调速 Action 定义与实现，以及候选 Core 的车辆命令翻译和安全策略；生产 state/command 继续使用现有 telemetry adapters 和唯一 CommandBroker writer |
| P3-03 Action 分类 | Vehicle-specific：`takeoff`、`land`、`change_speed`。Application-specific：`goto_waypoint`、`target_lock`、`align_descend`、`payload_release`、`select_drop_targets`、`gps_capture_view`、`gps_fuse_views`、`gps_target_lock`。Common：当前无可安全泛化的现有 Action |
| P3-04 Registry | `SystemRunner` 组合 Core Actions（当前空）+ MultirotorPlugin.actions + Application Actions，生成唯一 ActionRegistry 与 Web specs；候选 Core 组合入口显式接收此 catalog、车辆翻译器和安全策略；旧目录导入保留兼容 |
| P3-05 Capability | Mission 全步骤和 Action Lab 单 Action 在授权/启动前校验支持集合；候选 `MissionCompiler` 可注入相同校验。Rover 能力集合对 `takeoff` 必须失败 |

静态能力只表明插件支持，不替代当前连接、定位、Field GPS 前置条件、运行授权或执行 Safety。没有新增 Rover/Fixed Wing/VTOL 控制，也没有切换候选 Core owner。当前生产命令仍从 `ActionRuntimeService → ActionDispatcher → ActionSafetyPipeline → LinkManager → CommandBroker` 发送，不产生第二 writer。P4/P6 仍需继续拆分协议、传输和比赛 Field 语义。

## 测试与遗留

P3 针对性测试覆盖 Action 类实际归属、重复注册拒绝、Rover 起飞能力拒绝且无授权/执行、Multirotor 原 Action 列表不变，以及候选 Mission 编译拒绝。生产安全、CommandBroker、调度、Web 与已有 Action 回归仍需与后续阶段一起持续执行。

本轮最终全量执行为 718 passed、3 failed。三项失败均是本轮未修改文件与既有断言的冲突：`tests/contracts/test_strict_app_config.py` 要求 `rk3588-real/profile.yaml` 少于 20 行，实际 40 行；`tests/contracts/test_subflow_architecture.py` 要求 `align_descend.py` 少于 350 行，实际 653 行；`test_goto_reaches_target_and_releases_active_action` 的 4 次 tick 预期已完成，与既有 `settle_time_s=1.0` 默认值冲突。排除这三个用例（profile 同一参数化测试两例一并排除）后为 717 passed、4 deselected。本阶段没有为了使这些断言通过而改变配置或飞行行为。
