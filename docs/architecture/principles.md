# V1 架构原则

**状态：Frozen Target Architecture。** 以下为后续实现必须遵守的 Architecture Invariants；当前源码是否完全满足，见[当前实现](../migration/current_state.md)。

1. **Core 不知道具体车辆。** 通用 Core 不依赖 Multirotor、Rover、Fixed Wing、VTOL、ArduPilot、PX4、RK3588、CUADC、MAVLink、USB 或 WebRTC。不得在 Core 中用 `if vehicle_type == "rover"` 一类分支承载车辆差异；通过 Vehicle Plugin / Contract 注入。
2. **Action 是自主系统能力 API。** Action 提前实现、测试、注册，明确参数 Schema、输入输出与 Safety 约束。人写 Mission、LLM、Rule Planner 或 Agent 都只能组合已注册 Action，不能动态创造底层控制能力。能力由 VehicleCapabilities 限定。
3. **Mission 只编排。** 它管理 Action 顺序、参数引用、条件、retry、branch、failure policy 和 lifecycle；不处理 MAVLink、电机、PWM、串口、UDP、轨迹控制或 LiDAR Driver。
4. **Planning 与 Guidance 分离。** Planning 回答“应该怎么走”，包括全局或局部规划、避障、轨迹与任务方案；Guidance 回答“当前向哪里运动”，包括位置、速度、航向和目标跟踪。两者都不能绕过 Execution / Safety。
5. **Execution / Safety 是唯一运动出口。** Action 的 Typed Effect / Command Intent 经 Execution、Authorization、Safety 才能访问 VehicleCommandPort。Safety 保留最终拒绝或停止权。
6. **状态与控制分离。** Sensor 不做 Mission 决策；Perception 不直接控制 Vehicle；高级层优先读 WorldSnapshot，而不是自行连接硬件。
7. **Protocol 与 Transport 分离。** Protocol 解释消息含义；Transport 只负责字节 I/O。相同 Protocol 可复用不同 Transport。
8. **Environment 独立于 Mission 和 Vehicle 控制。** 场地、地图、区域和地理参考是场景 Profile，不是车辆或任务逻辑。
9. **Deployment 只改变位置。** onboard、server 和 hybrid 保持同一业务语义与 Safety 权限边界；Gateway 是设备与通信基础设施。
10. **CUADC 是示例。** CUADC 2026、RK3588、ArduPilot、YOLO/RKNN 均只能作为当前实现或具体 Profile / backend 说明，不能成为框架前提。

禁止的控制捷径包括 `LLM → MAVLink`、`VLM → VehicleCommand`、`YOLO → Flight Controller`、`Mission → pymavlink`、`Planner → raw serial` 和 `Web router → raw servo`。可执行的依赖红线见[依赖规则](dependency_rules.md)。
