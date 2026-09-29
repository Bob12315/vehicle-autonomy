# P4 协议与传输拆分

## 边界和当前生产路径

**Vehicle** 表示命令对车辆的含义，例如 `SetServo(channel, pwm)`、`BodyVelocity` 和 `StopMotion`。**Protocol** 表示如何用 MAVLink 消息表达命令、解读 ACK、heartbeat 与遥测。**Transport** 只负责字节在 Serial、UDP 或 TCP 上的移动，不认识 VehicleCommand、Mission 或 MAVLink。

当前生产链保持：`ActionRuntimeService → ActionDispatcher → ActionSafetyPipeline → LinkManager → CommandBroker → MavlinkEnvelopeWriter → CommandSender → MavlinkClient/pymavlink`。`executor.send_commands: false` 仍为默认；系统 SEND 与 Action send-actions 双门禁、broker generation / cancellation / ACK 生命周期和连续 BODY_NED stop 行为未改。

`vehicles/multirotor/adapter/mavlink.py` 把 typed `VehicleCommand` 转为现有 sender 输入。`SetServo` 是车辆/执行器语义；`protocols/mavlink/codec.py` 将其编码为 `MAV_CMD_DO_SET_SERVO`，没有改变 payload release 路径。`vehicles/multirotor/state/mavlink_fields.py` 处理 Copter 模式、GPS 有效性等车辆状态解释，`vehicles/multirotor/state/mavlink_adapter.py` 从 StateCache 的一致性 publication 映射为 `VehicleStateSnapshot`。接收器优先覆盖 Mission / Web / Safety 已消费的 heartbeat、attitude、global/local position、battery/GPS、gimbal 字段。

## 分层位置

| 层 | 当前 owner | 边界 |
| --- | --- | --- |
| Vehicle semantics | `contracts/platform/vehicle_commands.py`、Multirotor plugin | 不 import pymavlink；Action / Mission 不含 MAVLink 命令号 |
| Vehicle ↔ MAVLink | `vehicles/multirotor/adapter/mavlink.py`、`vehicles/multirotor/state/` | 命令转换、Copter 状态解释；不持有连接或 writer |
| MAVLink protocol | `protocols/mavlink/{connection,codec,messages,heartbeat,ack,commands}.py` | 连接兼容封装、COMMAND_LONG / message rate 编码、ACK 字段解码、heartbeat 和消息字段 |
| Byte transport | `infrastructure/transports/{base,spec,serial,udp,tcp}.py` | 同步 `open/close/read/write/is_open/health`；无协议、车辆或业务 import |
| Link lifecycle | `telemetry_link/link_manager.py:SourceRuntime` 与 `LinkManager` | 每个 source 的 connect / reconnect / timeout / worker 生命周期；active source 切换与 cancel |
| Command lifecycle | `telemetry_link/command_broker.py` 与 `ack_router.py` | admission、单车辆命令 writer、generation、cancel、ACK correlation、quarantine |

`real` / `sitl` 是 SourceId；`dual` 同时维持两条 source。三者不是 transport。`telemetry_link/config.py:resolve_vehicle_link` 将旧 EndpointConfig 解析为独立的 `VehicleLinkProfile(source, protocol, TransportSpec)`；`LinkManager` 在每条 source 的组合点完成选择。`eth` 是旧配置别名，实际解析为 UDP 或 TCP。USB 直连和无线数传只要都呈现 `/dev/ttyUSB*` 或 `/dev/ttyACM*`，就使用同一 `SerialTransport`。

## 渐进迁移的兼容债务

生产 `MavlinkClient` 目前仍通过 `pymavlink.mavlink_connection` 打开连接，pymavlink 同时拥有字节传输和帧解析。新 `ByteTransport` 实现是明确的底层契约，**尚未接入生产 MAVLink 字节流**；不能声称已实现 raw-byte parser 或任意协议的即插即用。未来接入时需要替换 `protocols/mavlink/connection.py` 的兼容封装，同时维持 broker 的唯一车辆命令 writer。

`CommandSender` 仍保留若干 MAVLink `SET_POSITION_TARGET_*`、gimbal 和 legacy queue 编码；通用 `COMMAND_LONG`、`SET_SERVO`、消息频率请求已委托 `protocols/mavlink/codec.py`。`TelemetryReceiver` 仍按 MAVLink 消息类型填充 StateCache；ACK 字段和 landed-state 解码已移到协议层，车辆状态语义和 DTO 投影移到 Multirotor 层。P4 时的 `telemetry_link/telemetry_parser.py`、`mavlink_state_adapter.py` re-export facade 已在后续调用方切换后删除。生产 `telemetry_link/` 其余生命周期与 writer 仍在使用，不能整体删除。

启动时消息频率设置是链路协议初始化请求，在 broker worker 启动前由 `SourceRuntime` 通过当前 sender 直发，并使用 ACK quarantine。它不是 Mission/Action 车辆命令，但仍是物理写入例外；见 [P4 writer audit](p4_writer_audit.md)。后续若收敛为同一物理写入队列，必须保留 ACK quarantine 与初始化顺序。

## 替换边界

- USB Serial 改为 UDP：修改配置中的连接类型和端点；Vehicle、Mission、Action 代码无需改动。
- 新增非 MAVLink 车辆协议：Core、Mission、Action 的 typed contract 无需改动；必须实现新协议会话/编码器、对应 Vehicle adapter 和遥测映射，并在 composition 选择新后端。目前 composition 只注册 MAVLink，尚不能仅改配置启用未知协议。
- P5 建议仅处理感知输入与 perception adapter，保留这里的 Vehicle Link 字节传输范围；Server networking、WebRTC / 视频传输不在 P4。

## P4 验证记录

`tests` 全量执行：737 passed、3 failed。三个失败均与 P4 无关且在阶段开始前已记录：`rk3588-real` profile 行数限制、`align_descend.py` 行数限制、goto waypoint 的 `settle_time` 预期。P4 专项及安全链选择测试 94 passed；`scripts/validate_architecture_boundaries.py`、`scripts/validate_stable_core.py` 和 `git diff --check` 均通过。测试未连接真实飞控。
