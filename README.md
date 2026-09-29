# Vehicle Autonomy Framework

Vehicle Autonomy Framework 是面向 Multirotor UAV、Rover / UGV、Fixed Wing、VTOL 及后续自主移动平台的模块化自主系统框架。**V1 Frozen Target Architecture 已冻结；当前源码尚未完全迁移。** 本仓库现有可运行实现仍主要来自 CUADC 2026 多旋翼项目。

## What it is

框架定义 Vehicle、Sensor、Perception、Localization、Mapping、World Model、Intelligence、Mission、Action、Planning、Guidance、Execution、Safety、Protocol、Transport、Environment 与 Deployment 的职责和连接方式。冻结架构是后续开发的设计约束，并不声明当前所有车辆或部署方式已经可用。

## Design goals

- 通过 Contract 与 Vehicle Plugin 隔离车辆差异，避免把机型判断写入 Core。
- 让不同来源的 Mission 复用经过注册、测试和 Safety 约束的 Action。
- 将状态理解与运动控制分开，保留唯一受授权和 Safety 裁决的控制出口。
- 让 Deployment 决定组件运行位置，而不改变业务语义。

## Architecture

```text
Operator / External System → Application ─┬→ Intelligence ─┐
                                           └→ Mission ───────┴→ Action
                                                              ↓
                                                    Planning / Guidance
                                                              ↓
                                                  Effect → Execution
                                                              ↓
                                                Authorization → Safety
                                                              ↓
                                               Vehicle Plugin → Protocol
                                                              ↓
                                                   Transport → Hardware

Sensors → Perception / Localization / Mapping → World Model
Environment ────────────────────────────────────→ World Model
World Model → Intelligence / Mission / Planning
```

完整图和依赖规则见[架构总览](docs/architecture/overview.md)与[依赖规则](docs/architecture/dependency_rules.md)。

## Core concepts

| 概念 | V1 职责 |
| --- | --- |
| World Model | 发布系统对车辆、对象、地图及环境的统一状态理解 |
| Mission / Action | Mission 编排已注册 Action；Action 是受约束的原子能力 API |
| Planning / Guidance | 分别决定路径或方案，以及当前运动目标 |
| Execution / Safety | 对 Effect 执行授权和最终安全裁决，作为唯一运动出口 |
| Vehicle Plugin | 提供能力、状态映射、车辆专用行为及命令转换 |
| Sensor / Perception | 采集标准化数据，并产生结构化 Observation |
| Protocol / Transport | 分别解释消息语义，以及传输字节 |
| Environment | 表达坐标、地图、区域及静态场景信息 |
| Deployment / Gateway | 选择 onboard、server 或 hybrid 布置；Gateway 承接远端物理设备 |
| Intelligence | 可提出 Intent 或 MissionProposal，不能直接发送车辆命令 |

## Supported / planned vehicle types

V1 目标涵盖 Multirotor、Rover / UGV、Fixed Wing 和 VTOL。**当前实现主要是 Multirotor；其他类型是架构预留，不能视为已支持。** 具体 Action 是否可用，由 VehicleCapabilities 与 Mission validation 判定。

## Current implementation status

当前 Action Mission、Web UI、telemetry、Safety、YOLO/RKNN 等实现仍有 CUADC 2026、ArduPilot、RK3588 和比赛场地语义。当前实际发送链与目标链的区别见[现状说明](docs/migration/current_state.md)。RK3588 是当前一种 Deployment / Compute Profile，ArduPilot 是一种 Vehicle / Protocol backend，YOLO/RKNN 是一种 Perception implementation；它们都不是通用 Core 的前提。

## Example: CUADC 2026

CUADC 2026 是项目的历史来源及一个具体 Example Application。它把 Multirotor、MAVLink、Camera、YOLO/RKNN、CUADC Environment、rescue Mission 和 RK3588 onboard Deployment 组合在一起。参见[示例映射](docs/examples/cuadc_2026.md)。

## Documentation

[文档入口](docs/README.md)给出阅读顺序。架构文档定义 V1 Frozen Target；`docs/migration/` 描述当前源码与未来迁移原则。Coding Agent 还须阅读 [AGENTS.md](AGENTS.md)。

## Safety notice

当前实现可能连接真实车辆。`config/app.yaml` 中 `executor.send_commands: false` 是当前默认值；现有系统 SEND 与 Action 授权双门控及连续命令停止行为必须保留。冻结目标中的 Execution / Safety 边界不能被任何 Mission、AI、Web 或感知模块绕过。本轮文档重构不改变运行行为，也不授予实机操作权限。
