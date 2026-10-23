# 阶段一遥测增量合同

VehicleStateSnapshot 的 V1.1 生产者增加可选 `telemetry` 字段；旧构造位置参数、
V1.0 模式和原有 pose/twist/operation/battery 安全消费语义兼容。没有改变冻结的
授权、命令、坐标、时效阈值、Stop 或 Mission 合同。七模块归属：只读类型在
contracts.vehicle，协议事实及标准化在 vehicles.ardupilot，显式装配在 app。

`VehicleTelemetrySnapshot` 绑定 source system/component 和 link session，逐消息提供：

- 原始消息名、归一化的具名不可变值、frame、quality。
- captured_at 与 received_at 独立；只有已有仿真源时钟可以限定的消息具有采样时间。
- MISSING / VALID / STALE / INVALID / UNKNOWN_CAPTURE_TIME；receive_fresh 单列。
- 观测、重复、倒序、无效计数。重复/倒序不会替换有效样本或更新时效。

Heartbeat、EKF_STATUS_REPORT、SYS_STATUS、POWER_STATUS、COMMAND_ACK、STATUSTEXT 没有可限定的
传感器采样时间，明确保持 captured_at=null；新接收仅表示收到事件。
STATUSTEXT 保留 id/chunk_seq，不把一个分块伪装成完整长告警。
GPS fix/卫星/HDOP 等保留缺失与协议 sentinel。缺失 EKF 或告警不能伪造正常值。

ATTITUDE 表示 ENU 中的 FLU 姿态，角速度表示车体 FLU；LOCAL_POSITION_NED 的
位置/线速度转为 ENU，GLOBAL_POSITION_INT 保留地理位置及 ENU 速度。
Rover 原有 GPS_GLOBAL_ORIGIN 局部投影仍用于控制位姿；是否提供 LOCAL_POSITION_NED 按当前 AP 实际报文记录，不虚构缺失消息。

`telemetry_snapshot()` 以查询时间重新评估字段年龄，不更新任何传感器采样时间或
控制快照发布时间。诊断不是控制授权；所有原有 Safety/Authority/唯一 Writer 检查继续执行。
新连接创建新的 monitor，旧 ACK、告警、计数和传感器状态均不继承。

协议修复：ACK 目标扩展字段为其他控制器时不能匹配本控制器请求；受 ACK 栅栏
阻塞的队列项仍须按原期限拒绝。缺失 ACK 和迟到 ACK 不提升 UNKNOWN 结果。

POWER_STATUS 保留飞控上报的 5V/舵机电源轨电压和 flags；不根据某个电压值推定硬件或供电正常。Copter 仿真参数增加 MAV1_EXTRA3=2，仅打开既有 EKF 状态流，不改变安全或运动参数。
