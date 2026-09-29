# P4 车辆链路 writer 审计

审计范围：`rg 'send_raw_message|command_long_send|command_int_send|set_position_target_.*_send|mavlink_connection|LinkManager'`，覆盖 app、application、execution、missions、vehicles、telemetry_link、protocols、infrastructure、tools、scripts 和 tests。分类以当前默认运行路径为准。

| 入口 / 写入点 | 分类 | 到达路径和处理 |
| --- | --- | --- |
| `telemetry_link/command_broker.py:CommandBrokerWorker` → `mavlink_encoder.py:MavlinkEnvelopeWriter` → `command_sender.py` | PRODUCTION | 唯一常规车辆命令 writer；broker admission、generation、late gate、cancel / barrier 在编码之前，sender 的 thread 在 v2 模式下不启动 |
| `protocols/mavlink/codec.py:send_command_long/send_set_servo`、`command_sender.py` 的 `SET_POSITION_TARGET_*` / gimbal send | PRODUCTION encoding sink | 仅由上述 writer 调用；`SetServo` 对应 `MAV_CMD_DO_SET_SERVO`，没有 `release_payload` / RC override 生产路径 |
| `telemetry_link/link_manager.py:SourceRuntime._request_message_interval(direct=True)` | LINK INITIALIZATION EXCEPTION | broker worker 启动前设置 telemetry rate；共享当前 sender / pymavlink sink，注册并隔离 `MAV_CMD_SET_MESSAGE_INTERVAL` ACK。不是 Action 控制，但物理写入尚未收敛至 broker 队列 |
| `telemetry_link/command_sender.py:run`、旧 `CommandQueue` | LEGACY | 仅 `v2_writer_enabled: false` 分支启动；默认配置为 v2 true。保留兼容，后续删除条件见 P4 文档 |
| `telemetry_link/command_dispatcher.py` | DIAGNOSTIC | 文本命令经 LinkManager；不是正式 Web UI / Action 主线。由 `tools/telemetry_debug.py` 使用 |
| `tools/telemetry_debug.py` | DIAGNOSTIC | 默认只读：`diagnostic_read_only` 不创建 sender/broker，也不发消息频率请求；只有显式 `--allow-send` 才启用旧文本命令通道。这个 opt-in 不替代正式操作的 SEND / Action 双门禁，严禁作为正式操作入口 |
| `scripts/validate_p0_sitl.py` | SITL TOOL | 显式 SITL 验证脚本，调用 LinkManager；不属于正式 app 入口 |
| `tests/**` 中 fake writer / MAVLink send | TEST | 假连接和录制调用验证；不连接真飞控 |
| `infrastructure/transports/*:write` | CONTRACT ONLY | 原始字节实现，目前不接入生产 MAVLink connection；无命令语义 |

`app/bootstrap.py` 创建正式 `LinkManager`；`yolo_app/` 没有 MAVLink writer。非测试代码中未发现其他 `mavlink_connection`、`send_raw_message` 或直接 `.mav.*_send` 的调用点。当前默认生产中，车辆命令只有 broker 授权路径；链路初始化消息频率请求是已标明的物理写入例外，不能宣称所有 MAVLink 帧均经 broker。

默认配置核对：`config/app.yaml` 的 `executor.send_commands: false`；`config/telemetry.yaml` 的 `legacy_writer_enabled: false`、`v2_writer_enabled: true`。真实硬件发送仍需系统 SEND 与 Action send-actions 双门禁。诊断工具的 `--allow-send` 是独立开发工具的危险操作选项。
