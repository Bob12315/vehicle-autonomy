# Current Implementation：当前源码状态

**状态：Current Implementation，非 V1 目标架构。** 本文记录本轮文档重构时可从仓库识别的主要事实；后续改代码前仍须核对当时源码、配置与测试。V1 冻结架构见[总览](../architecture/overview.md)。

仓库仍大量来自 CUADC 2026 多旋翼救援项目：`config/action_missions/` 中有比赛 Mission 模板，`field/` 与 `config/field_profiles/` 含 Competition Field 语义，`yolo_app/` 使用 RKNNLite / RK3588 路线，`telemetry_link/` 以 ArduPilot / MAVLink 为主要现有后端。Web UI、Action、Fusion 与安全策略也有该应用的参数和词汇。它们是现有实现，不是通用 V1 框架的永久限制。

## 当前可保留的资产

| 资产 | 当前代表性位置 | 迁移时的定位 |
| --- | --- | --- |
| Action Mission 概念及模板 | `missions/`、`config/action_missions/` | 可作为 Mission / Action 基础，需与车辆能力解耦 |
| Action Runner、Action 实现 | `missions/common/actions/` | 保留经验证行为，逐步对齐 Action Contract |
| Execution、授权与 Safety | `execution/`、`application/` | 现有保护必须保留，目标唯一出口尚待迁移核对 |
| Web infrastructure | `web_ui/`、`application/web_services.py` | 作为 Application 入口资产 |
| telemetry implementation | `telemetry_link/` | 后续拆清 Vehicle / Protocol / Transport 边界 |
| YOLO implementation | `yolo_app/` | 一种 Perception implementation，不是通用要求 |
| CUADC Mission、Field | `config/action_missions/`、`field/` | Example Application / Environment Profile 来源 |

## 当前发送与目标的区别

现有 Action 发送主线包括 `ActionRuntimeService → ActionDispatcher → ActionSafetyPipeline → LinkManager → telemetry_link`。默认 `config/telemetry.yaml` 已启用 **v2 CommandBroker writer**，关闭 legacy sender；因此不能把整个 v2 平台发送链称为 shadow。`config/app.yaml` 的 `executor.send_commands` 当前默认 `false`；系统 SEND 和 Action 授权双门控、连续 BODY_NED stop/zero 与 stale 命令清理是现有必须保护的行为。另一方面，`contracts/core/`、`missions/core/`、`application/core/`、`execution/dispatcher_v2.py` 虽有实现，却没有从 `app/main.py → SystemRunner` 生产入口接管 Mission / Action Runtime。**平台 writer 的 v2 生产启用，不等于目标 Stable Core 生产 owner 已切换。** 详见[安全基线](safety_baseline.md)。

P2 已整理 Core 公共类型、Typed Effect 与统一 RuntimeInputSnapshot，并建立静态依赖测试。P3 已建立 Vehicle Contract、Multirotor Plugin、Action 分类、生产入口组合和任务启动能力预检；详见 [P2/P3 验收记录](p2_p3_acceptance.md)。`takeoff`、`land`、`change_speed` 的实现已在 `vehicles/multirotor/actions/`，旧路径是兼容导入。P4 已建立 Vehicle Link 的 Protocol / Transport 边界，但生产 pymavlink 连接仍合并帧解析和字节传输；详见 [P4 记录](p4_protocol_transport.md)。P5 已建立 CameraPort、PerceptionPort 绑定与最小 WorldSnapshot，生产旧视觉投影仍有兼容用途；详见 [P5 记录](p5_sensors_perception_world.md)。P6 已落地 Environment 契约、四种 Profile 的目录和 CUADC Field 只读适配器，但 Web Profile 选择、具体场地位置与 Mission 模板迁移未完成；详见 [P6 框架记录](p6_environment_framework.md)。P7 已建立 Deployment Profile、Gateway 和远端端口契约，但 server / hybrid 尚无生产实现；详见 [P7 框架记录](p7_deployment_gateway_framework.md)。P8 已建立 `applications/cuadc_2026/` 组合入口，Web 与校验脚本共用正式模板清单，候选 Core 不再导入 CUADC Environment；算法与参数仍保留旧路径，详见 [P8 框架记录](p8_cuadc_application_framework.md)。P9 已用 FakeRover 证明第二车型可接入候选 Core 与 World Model，但没有实车控制；详见 [P9 记录](p9_second_vehicle_proof.md)。Fixed Wing、VTOL、LLM/VLM Mission Producer、WebRTC Camera、LiDAR 等是目标范围，不是当前功能清单。

P0–P1 只处理文档；P2–P3 已修改 Contract、候选 Core 和生产 Action 装配代码，但没有改动 Mission JSON、Safety 参数、SEND 默认值或实际 writer 归属。[迁移原则](migration_principles.md)约束后续工作。
