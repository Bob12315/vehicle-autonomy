# P9 第二车型证明：FakeRover

**状态：仅离线架构证明；不是可控制的 Rover 后端。** 本轮继续遵循“只修改框架，具体细节之后完善”，新增 `vehicles/rover/`，没有修改 Core、Mission Runtime、World Model Core 或 Protocol 抽象，也没有连接实车。

| P9 项 | 当前实现 |
| --- | --- |
| Capabilities | `RoverPlugin` 声明 fake 的 `stop`、`drive_velocity`、`goto_ground`，不声明 `takeoff`。MissionCompiler 可复用现有能力校验钩子。 |
| State schema | 不可变 `RoverState` 表达平面位置、航向、前向速度与连接/时效；投影为现有 `VehicleStateSnapshot`，飞行、GPS、云台字段明确为空。WorldModel 可直接消费。 |
| Fake adapter | `FakeRoverAdapter` 提供内存状态和 VehicleCommandPort 形状；所有 submit 都拒绝，cancel 的 stop barrier 返回 `STOP_UNDELIVERABLE`，不冒称物理停车。fake 用 `sitl` SourceId 适配当前候选 Core 的离线来源枚举，不连接 ArduPilot SITL。 |
| Action registry | 三个 Rover Action 有独立参数 Schema，能进入现有 Action Catalog 和 Mission 编译。由于尚无 Rover 命令语义/协议，Action 更新会以 `fake_rover_no_control_backend` 失败，绝不产生 Effect。 |
| Safety schema | `RoverSafetyConfig` 定义速度/转向速率上限形状；`RoverSafetyPolicy` 当前拒绝全部控制 Effect。`translate_effect` 也拒绝，因此即使误开启 SEND，fake plugin 仍无物理 writer。 |

离线测试用同一 `build_core_runtime`、`MissionCompiler` 与 `WorldModel` 装配 FakeRover，并验证 SEND 初始关闭、Rover 状态进入 WorldSnapshot、`takeoff` 不可注册、`drive_velocity` 失败且无 command submission。通用层静态检查禁止引用 `vehicles.rover`。

验证结果：P9 专项测试 `4 passed`；架构边界与 Stable Core 检查通过；全量回归 `766 passed, 3 failed`。三个失败均与 P8 基线相同：`rk3588-real` Profile 行数约束、`align_descend` 行数约束、`goto_waypoint` 完成状态断言；本轮未修改对应源码。

下一步如要接实车，需要先定义 Rover 专用命令语义和协议/传输适配、停车与断链安全策略、运动包线、实际状态来源及相应 SITL/实机验证。当前 `BodyVelocityTarget` / MAVLink 飞行命令不被当作 Rover 驱动的替代实现。生产 CUADC 多旋翼 Action、SEND 双门控、唯一 CommandBroker writer 和连续命令 stop/zero 行为保持不变。
