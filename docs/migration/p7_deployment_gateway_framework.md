# P7 Deployment / Gateway 框架边界

**状态：P7 框架契约已落地；生产只保持现有 onboard 路径。** 本轮延续“只修改框架，具体细节之后完善”的范围。没有新建远端命令 writer、Gateway 服务、WebRTC 或公网控制链。

| 子项 | 已实现 | 后续实现 |
| --- | --- | --- |
| P7-01 Deployment Profile | `deployment/` 定义 `onboard`、`server`、`hybrid` 模式和逐组件 placement；目录仅将 `onboard_rk3588` 标记为 available。校验要求 Safety 与 Vehicle Link 留在车端，远端模式须有车端 Gateway | server / hybrid 的实际进程拓扑、配置加载和断链策略 |
| P7-02 Vehicle Gateway Contract | `gateway/contracts.py` 定义 telemetry/sensor 转发、命令接收、链路健康与 watchdog 边界；命令入口只接收现有 `VehicleCommandEnvelope`，契约要求车端再次验证授权、SEND、lease、session、generation、TTL | 本地 admission 实现、认证、可靠转发、watchdog 驱动 stop/clear 与实际设备接入 |
| P7-03 Server Transport Boundary | `RemoteVehicleLink`、`RemoteCameraSource` 定义服务端所见 Port；离线 fake 验证无本地安全入口时命令被拒绝、超时 watchdog 不冒称 stop 已送达 | 网络协议、端到端身份认证、时钟/序列同步、CameraFrame 编解码及 WebRTC |
| P7-04 Onboard Compatibility | `onboard_rk3588` 是具体 Profile，不是 Framework 的默认硬件假设；现有 SystemRunner、YOLO/RKNN、telemetry、systemd 部署路径均保持 | 将部署 Profile 接入实际启动配置与多节点装配；此时须重新验证唯一 writer 与安全链 |

`available` 只表示当前 onboard 组合有实际运行路径；它不代表新 Profile loader 或通用设备驱动已投入生产。server / hybrid 是明确不可选的目标 Profile。Gateway 没有 Mission、Planning 或 AI 职责；RemoteVehicleLink 只能在受授权的 Execution / Safety 装配点使用，不能直接交给 Mission、Web 或感知模块。

现有生产链继续走 `ActionRuntimeService → ActionDispatcher → ActionSafetyPipeline → LinkManager → telemetry_link`。`executor.send_commands: false`、SEND / Action 双门控、broker 的时效和 generation 检查、连续 BODY_NED stop/zero 均未改。`GatewayWatchdogStatus` 分开记录“请求 stop”和“确认 stop”；断链不能保证物理 stop 已送达。

## 验证

离线测试覆盖部署 Profile 可用性与位置约束、远端 fake 的拒绝默认值、watchdog 状态语义，以及 Gateway/Deployment 不导入 Mission 或硬件实现。全量测试结果为 758 passed、3 failed；3 项失败均在 P7 前已存在，分别涉及 strict profile 行数限制、align_descend 行数限制和 goto settle time。架构边界及稳定核心校验通过。测试没有建立远端连接或访问真实飞控。
