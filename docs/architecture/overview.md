# V1 架构总览

**状态：Frozen Target Architecture。** 本图定义后续实现必须收敛的顶层边界，不表示当前源码已具备全部模块。实际状态见[当前实现](../migration/current_state.md)。

## 控制路径

```text
                    Operator / External System
                              │
                              ▼
                         Application
                         ┌────┴────┐
                         ▼         ▼
                  Intelligence   Mission
                  LLM/VLM/Policy    │
                         │         ▼
                         └──────→ Action
                                    │
                                    ▼
                           Planning / Guidance
                                    │
                                    ▼
                             Typed Effect
                                    │
                                    ▼
                   Execution → Authorization → Safety
                                                  │
                                                  ▼
                                        VehicleCommandPort
                                                  │
                                                  ▼
                                            Vehicle Plugin
                                                  │
                                                  ▼
                                        Protocol → Transport
                                                  │
                                                  ▼
                                           Physical Vehicle
```

Application 是人工与外部系统入口，提供 Web UI、API、WebSocket、配置、系统状态、start/stop/reset、Mission 操作和 Profile 选择。它仅调用 Use Case / Core API。Intelligence 只提供语义、Intent 或 MissionProposal；其结果经过 Mission / Action 边界。Planning 决定路径或方案，Guidance 决定当下运动目标。所有实际运动经 Execution、Authorization、Safety 与 VehicleCommandPort。详情见[Mission / Action](../core/mission_action.md)和[Execution / Safety](../core/execution_safety.md)。

## 状态路径

```text
Physical Sensors → Sensor Adapters → Perception / Localization / Mapping
                                                  │
                                                  ▼
                                             World Model
                                            ┌────┼────┐
                                            ▼    ▼    ▼
                                    Intelligence Mission Planning

Environment ────────────────────────────────→ World Model
```

Sensor Adapter 采集与标准化数据；Perception、Localization、Mapping 产生可解释的 Observation、状态估计和空间表示。World Model 汇聚成 WorldSnapshot，供上层优先读取。Environment 提供场景信息，不产生车辆命令。详见[数据流](data_flow.md)及[World Model](../core/world_model.md)。

## 横向关系

Deployment 选择组件位于 onboard、server 或 hybrid；远端设备接入由 Gateway 承接。部署只改变位置、链路和故障处理方式，不改变 Mission、Action、Safety 的职责。Vehicle Plugin 处理车辆差异；Protocol 解释消息；Transport 传输字节。参见[部署与 Gateway](../platform/deployment_gateway.md)、[Vehicle Plugin](../platform/vehicle_plugin.md)及[Protocol / Transport](../platform/protocol_transport.md)。
