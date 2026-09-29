# P4-01 telemetry_link 职责清点

**状态：迁移前源码清点。** 本表按 `app/main.py → SystemRunner → ServiceManager` 的默认生产路径和独立诊断入口区分 owner；本步不移动代码。`real` / `sitl` 是来源身份，`dual` 是同时维护两条来源，均不是 Serial / UDP / TCP Transport。

| Current symbol/file | Responsibility | Current caller | Target layer | Migration action |
| --- | --- | --- | --- | --- |
| `app/bootstrap.py:ServiceManager` | D/G：创建 LinkManager、三个端口 facade，持有服务生命周期 | `SystemRunner` | Application composition root | WRAP |
| `telemetry_link/config.py:EndpointConfig/TelemetryConfig` | G：source、连接地址、速率、超时、writer 选择和状态 UDP 混合 | app config、LinkManager、工具 | Application 配置兼容解析 + TransportSpec | EXTRACT |
| `telemetry_link/link_manager.py:LinkManager` | A/D/E：active source、Vehicle 语义方法、broker 转发、stop/cancel | ActionDispatcher、SystemControl、ServiceManager | Vehicle adapter + LinkSession facade | WRAP；DELETE-LATER |
| `link_manager.py:SourceRuntime` | D/E：连接、heartbeat bootstrap、worker 创建/停止、重连 | LinkManager | LinkSession / composition | EXTRACT |
| `link_manager.py:_request_message_interval` | B/E：MAV_CMD_SET_MESSAGE_INTERVAL 编码请求及 ACK quarantine | SourceRuntime 启动 | MAVLink protocol + link initialization | EXTRACT |
| `telemetry_link/mavlink_client.py:open_mavlink_connection` | B/C：pymavlink 同时打开和解析 Serial/UDP/TCP | MavlinkClient | pymavlink compatibility adapter | WRAP |
| `mavlink_client.py:MavlinkClient` | B/D：连接、autopilot heartbeat、target identity、raw send/receive | SourceRuntime、Receiver、Sender | MAVLink protocol session + LinkSession | EXTRACT |
| `telemetry_link/command_sender.py:CommandSender` | B/E：legacy queue thread 与 MAVLink 编码交织；默认 v2 仅复用编码方法，线程未启动 | SourceRuntime、MavlinkEnvelopeWriter | Protocol encoder + legacy facade | EXTRACT；DELETE-LATER |
| `telemetry_link/mavlink_encoder.py:MavlinkEnvelopeWriter` | A/B/E：typed VehicleCommand → legacy ActionCommand/ControlCommand、ACK slot、实际 writer 调用 | CommandBroker | Multirotor MAVLink adapter + protocol encoder | EXTRACT |
| `telemetry_link/mavlink_command_adapter.py` | A/E：旧 Action/Control 转 typed envelope，写上下文和 generation | LinkManager | Vehicle/Execution compatibility adapter | WRAP |
| `telemetry_link/command_broker.py` | E：admission、幂等、source/session/generation、cancel、late gate、唯一 writer worker | SourceRuntime / LinkManager | Execution platform broker | KEEP |
| `telemetry_link/ack_router.py` | B/E：以 MAV command/source/session 关联 ACK，管理 early ACK、quarantine、超时并回报 broker | Receiver / writer | Protocol ACK decode + Broker correlation | EXTRACT（仅 decode）；KEEP（lifecycle） |
| `telemetry_link/command_queue.py` | E：legacy control/action queue | Sender、LinkManager | legacy queue | DELETE-LATER |
| `telemetry_link/telemetry_receiver.py` | B/D/F：按 MAVLink message type 解读并更新 StateCache、ACK router、timeout | SourceRuntime | Protocol decode + Vehicle state mapper + LinkSession health | EXTRACT |
| `telemetry_link/telemetry_parser.py` | A/B/F：Copter mode、armed、位置/GPS/gimbal 解析 | Receiver | Multirotor state mapper + MAVLink message decoder | EXTRACT |
| `telemetry_link/state_cache.py` | D/F：source session、atomic publication、状态 freshness、断连/重连 | Receiver、LinkManager、state adapter | LinkSession publication + Vehicle state projection | WRAP |
| `telemetry_link/mavlink_state_adapter.py` | F：StateCache publication → `VehicleStateSnapshot` | `VehicleStateAdapter` | Multirotor state mapper | MOVE-LATER |
| `telemetry_link/ports.py` | A/F：生产读写 facade，无独立 writer | ServiceManager、Execution、Web | Vehicle ports compatibility | WRAP |
| `telemetry_link/state_publisher.py` / `attitude_udp_publisher.py` | F/H：只读状态 UDP 发布 | 工具 / virtual nadir | Telemetry output adapter | KEEP |
| `telemetry_link/command_dispatcher.py` | H/A：文本诊断可请求 arm/takeoff/servo | telemetry_debug 等工具 | Diagnostic adapter；需显式写入 opt-in | WRAP |
| `execution/dispatcher.py` / `safety_pipeline.py` | E：Action SEND、授权、包线、连续 stop | ActionRuntimeService | Execution / Safety | KEEP |
| `execution/dispatcher_v2.py` | E：候选 Core typed Effect 分发，未接生产 owner | `application/core/runtime.py` | Core execution adapter | KEEP |
| `vehicles/multirotor/commands/translator.py` | A：候选 Effect → VehicleCommand | MultirotorPlugin | Vehicle plugin | KEEP |
| `contracts/platform/vehicle_commands.py` / `contracts/vehicle/` | A/E：typed command DTO、端口和能力，无 pymavlink 对象 | broker、插件、候选 Core | Vehicle Contract | KEEP |
| `tools/telemetry_debug.py` | H：独立 stdin 诊断入口，可经 LinkManager 请求命令 | 人工开发工具 | 默认只读、显式写入 opt-in | WRAP |
| `tests/unit/adapters/test_command_broker.py` / `tests/integration/test_telemetry_link.py` | E/F：broker、ACK、source、连接、写入回归 | pytest | Contract / integration tests | KEEP |

## 当前关键行为

- `MavlinkClient.connect` 从 EndpointConfig 的 `serial`、`udp`、`tcp`、`eth` 选择 pymavlink connection string。`eth` 是配置别名，实际落在 TCP 或 UDP；无线数传若表现为 `/dev/ttyUSB*` / `/dev/ttyACM*`，实际类型仍为 Serial。
- `SourceRuntime` 为 `real` / `sitl` 各保留连接、状态、session 和 broker；`dual` 同时启动两个 source，LinkManager 只向 active source 暴露状态与控制。source 切换会取消旧 source 命令。
- 默认 `legacy_writer_enabled: false`、`v2_writer_enabled: true`。`CommandBrokerWorker → MavlinkEnvelopeWriter → CommandSender` 是唯一车辆命令 writer；启动时消息频率请求是链路初始化直发，必须单独审计。
- `TelemetryReceiver` 消费 HEARTBEAT、ATTITUDE、GLOBAL_POSITION_INT、LOCAL_POSITION_NED、VFR_HUD、SYS_STATUS、GPS_RAW_INT 等消息；`MavlinkVehicleStateAdapter` 从 StateCache 的一致性 publication 生成 VehicleStateSnapshot。COMMAND_ACK 的字段解析与 broker 的命令生命周期是不同职责。
- 独立 `telemetry_debug.py` 绕开 ActionSafetyPipeline；默认 v2 broker 的 send gate 仍关闭，但 legacy writer 模式会增大风险。P4 必须将该工具改为默认只读。

## 迁移顺序

先建立 TransportSpec / ByteTransport 与配置兼容解析；再封装 pymavlink 连接、抽出 MAVLink decode/encode 和 Multirotor 映射；随后收敛 source 生命周期及诊断写入门禁。每次切换保留旧 facade 和单 writer 回归，最后才考虑删除 `telemetry_link/`。
