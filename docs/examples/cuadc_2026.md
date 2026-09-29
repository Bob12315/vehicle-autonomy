# CUADC 2026：历史来源与 Example Application

**状态：Current Application 与已落地应用组合的映射。** `applications/cuadc_2026/` 已集中声明现有组合与正式 Mission 模板；比赛算法、配置和生产控制链仍沿用当前实现，详见 [P8 记录](../migration/p8_cuadc_application_framework.md)。

当前仓库源于 CUADC 2026 多旋翼侦察与救援应用，包含 ArduPilot、RK3588、USB 下视相机、YOLO/RKNN、Competition Field 与 rescue Mission。它是框架的一个具体实例，不能代表框架的全部 Vehicle、Sensor 或 Deployment。

| 当前应用组成 | V1 架构归属 |
| --- | --- |
| 多旋翼与 ArduPilot | `vehicles/multirotor/` 的一种 Vehicle backend |
| MAVLink | `protocols/mavlink/` |
| Ethernet / Serial 链接 | Transport Profile；具体连接依现场配置 |
| USB Camera | `sensors/camera/` 的 Camera Adapter |
| YOLO / RKNN | `perception/detection/` 的一种实现 |
| CUADC Competition Field | `environments/` 下的 `cuadc_2026` Profile |
| 救援任务 | `missions/` 下的 `rescue_2026` Mission Profile |
| RK3588 机载计算 | `deployment/` 的 onboard Compute Profile |

```text
Deployment: onboard RK3588
Vehicle:    multirotor / ArduPilot
Protocol:   MAVLink
Transport:  Ethernet or Serial
Sensor:     USB Camera
Perception: YOLO / RKNN
Environment: cuadc_2026
Mission:    rescue_2026
```

上述组合现由 `CUADC_2026_PROFILE` 明确记录。它是当前应用的资产映射，仍有模块耦合和比赛专用逻辑，详见[当前状态](../migration/current_state.md)。
