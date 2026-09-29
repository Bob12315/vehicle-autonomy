# Vehicle Plugin 与 VehicleCapabilities

**状态：V1 冻结目标；P3 已建立 Multirotor Plugin 和生产 Action 组合，P9 已建立离线 FakeRover。** 其他车辆目前没有真实控制实现。`contracts/vehicle/` 提供能力、健康状态与插件协议，并复用现有 `contracts.platform.ports` 的 VehicleStatePort / VehicleCommandPort，避免引入第二套命令协议。

Vehicle Plugin 封装车辆专有语义：VehicleCapabilities、VehicleState mapping、车辆专用 Action、车辆专用 Safety 约束、Vehicle command translation、车辆配置和 health 语义。通用 Core 通过 Vehicle Contract 使用这些能力，不根据 `vehicle_type` 在核心代码中分支。通用 Safety 仍有最终裁决权；车辆专用 Safety 只能补充约束，不能绕过裁决。

| Vehicle | 可能的能力示例 |
| --- | --- |
| Multirotor | `takeoff`、`land`、`hover`、`goto`、`body_velocity`、`yaw` |
| Rover | `drive`、`reverse`、`turn`、`stop`、`follow_path` |
| Fixed Wing | `takeoff`、`goto`、`loiter`、`change_airspeed`、`rtl`、`land` |
| VTOL | 根据具体过渡与飞行模式声明能力，不能由名称推断 |

这些是目标能力示例，不表示当前均有实现。VehicleCapabilities 至少能表达起飞、降落、悬停、倒车、位置/速度/航向控制、载荷、云台和盘旋等支持情况。Mission validation 在运行前检查 Action 与 Capability 是否匹配；Web 也可用其展示可执行操作。详见[Mission / Action](../core/mission_action.md)。

Vehicle Adapter 负责“这句话对这辆车意味着什么”；Protocol 负责“消息怎么表达”；Transport 负责“字节怎么送达”。ArduPilot 可是一种 backend，不是 Core 的前提。见[Protocol / Transport](protocol_transport.md)。

## P3 当前落点

`vehicles/multirotor/actions/` 持有 `takeoff`、`land`、`change_speed` 的实际实现；旧 `missions/common/actions/` 兼容导入已删除。`MultirotorPlugin.actions` 提供这三个定义，`applications.cuadc_2026.composition` 在 `SystemRunner` 装配时合并它们与 CUADC Application Actions。当前没有独立的通用 Core Action；11 个现有 Action 均有车辆或应用语义。

`VehicleCapabilities` 是静态支持集合，不代表当前连接、定位或硬件健康；运行时健康由 `vehicles/multirotor/state/health.py` 根据既有快照映射。Mission / Action Lab 在运行授权和首个 Action 前按能力拒绝不支持的 Action；候选 Core 的 `MissionCompiler` 也提供同一校验钩子。它们不取代 SEND 双门控、ActionSafetyPipeline 或 v2 CommandBroker 的最终裁决。

`vehicles/multirotor/commands/translator.py` 和 `safety/policy.py` 持有候选 Core 当前使用的车辆命令翻译与车辆约束；`execution` 旧翻译导入路径已删除。候选 Core 组合入口必须显式注入 ActionCatalog、车辆翻译器与安全策略，不在 Core 中选择车辆类型。

P4 才会拆分 `telemetry_link` 中的协议与传输。当前生产 Multirotor 继续复用现有 `VehicleStateAdapter`、`VehicleCommandAdapter`、`LinkManager`、ActionSafetyPipeline 与单 writer `CommandBroker`，没有另起控制路径。候选 Core owner 仍未接管生产入口。
