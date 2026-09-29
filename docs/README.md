# 文档入口

Vehicle Autonomy Framework 面向多种自主移动平台。**V1 Frozen Target Architecture** 是后续设计、代码迁移与 Coding Agent 的架构依据；`Current Implementation` 是尚未完全迁移的源码事实；`Migration Work` 是将来逐边界实施的工作。架构图不等于完成状态。

## 阅读顺序

1. [根 README](../README.md)：项目定位与现状。
2. [架构总览](architecture/overview.md)：控制链、状态链和模块关系。
3. [架构原则](architecture/principles.md)：永久不变量。
4. [依赖规则](architecture/dependency_rules.md)：修改源码时的边界红线。
5. [当前状态](migration/current_state.md)：当前实际实现与缺口。
6. 按任务阅读以下专题。Coding Agent 还须阅读 [AGENTS.md](../AGENTS.md)。

## Frozen Architecture

| 主题 | 文档 |
| --- | --- |
| 总体与数据流 | [总览](architecture/overview.md) · [数据流](architecture/data_flow.md) · [目标目录](architecture/target_structure.md) |
| Core | [Mission / Action](core/mission_action.md) · [Execution / Safety](core/execution_safety.md) · [World Model](core/world_model.md) |
| Platform | [Vehicle Plugin](platform/vehicle_plugin.md) · [Sensors / Perception](platform/sensors_perception.md) · [Protocol / Transport](platform/protocol_transport.md) · [Environment](platform/environment.md) · [Deployment / Gateway](platform/deployment_gateway.md) |
| Intelligence | [权限边界](intelligence/boundaries.md) |

## Current Implementation / Migration Work

[V1 重构执行计划](migration/refactor_plan_v1.md)是 P0–P11 的阶段基线。[当前状态](migration/current_state.md)概述现有源码；P1 的[源码映射](migration/current_code_map.md)、[依赖审计](migration/dependency_audit.md)和[安全基线](migration/safety_baseline.md)提供源码证据。P2 的[Core 公共类型盘点](migration/p2_01_core_common_types.md)与[Typed Effect 边界盘点](migration/p2_02_effect_boundary.md)记录已有 Contract、生产兼容链及延后项；[P2/P3 验收记录](migration/p2_p3_acceptance.md)、[P4 Protocol / Transport](migration/p4_protocol_transport.md)、[P5 Sensors / Perception / World Model](migration/p5_sensors_perception_world.md)、[P6 Environment 框架边界](migration/p6_environment_framework.md)、[P7 Deployment / Gateway 框架边界](migration/p7_deployment_gateway_framework.md)、[P8 CUADC Application 框架边界](migration/p8_cuadc_application_framework.md)、[P9 FakeRover 第二车型证明](migration/p9_second_vehicle_proof.md)、[P10 旧路径删除门禁审计](migration/p10_legacy_cleanup.md)和[P11 Intelligence 预留](migration/p11_intelligence_reservation.md)记录已实施的迁移边界及兼容债务。[迁移原则](migration/migration_principles.md)约束迁移方法。[CUADC 2026 示例](examples/cuadc_2026.md)说明历史应用如何映射到目标架构。

如果文档中的目标与当前代码不同，新增设计遵守冻结架构；修复当前运行问题时还必须保护实际 Safety 行为，并先核对源码。迁移需要单独实施与验证。
