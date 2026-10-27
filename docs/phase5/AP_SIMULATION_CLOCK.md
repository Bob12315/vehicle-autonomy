# Phase 5 仿真源时间证据（开发阶段）

默认 SimulationSourceClock、Arm/Disarm 签名确认和安全期限保持原合同。
Phase 5 专用 owned Rover 配置可显式启用 source_time_sync。它要求接收签名、
公开 SERIAL0_BAUD=115 参数读回证据、独占存活仿真所有权和不超过 20 ms 的
owner 调度周期。原 profile 的 100 ms / 200 ms watchdog 合同不变；调度与
已验证的安全 profile 分离，调度只能比 profile 更快。没有实机控制入口。

TIMESYNC 查询仍经原 CommandPort、Authority 临界区、Codec 和唯一 Transport
写入；没有传感器/ROS 第二个 MAVLink Writer。编码只允许 tc1=0 的只读查询。
查询不授予系统或 Action SEND；统计必须区分协议帧与车辆控制帧。

本机受测 ArduPilot GCS_Common.cpp 的响应 tc1 是 AP 端源时间，ts1 回显请求
nonce。接收必须通过原持久化签名水位验证，nonce 单次使用且 RTT <=200 ms。
AP_HAL_SITL/UARTDriver.cpp 的 receive_time_constraint_us 会减去 UART 接收估时；
因此不能把 tc1 直接当作请求后的真实采样时刻。按公开波特率下界 57600、
64 字节保守帧长和唯一 Writer 在查询之后实际尝试写入的字节数，计算源时间
阈值上界。只有 boot 时间不小于该阈值的遥测才能使用请求发送时刻作为
**保守的采样时间下界**。这是保守年龄，不是精确采样时刻或速率拟合。

最多保存 64 个锚点、一个在途请求；旧遥测仍得到旧下界；源 boot 回退要求
新 timing/session epoch。新连接重建 nonce/时钟。ACK 和 HEARTBEAT 总是返回
无此时间证据，不能借 TIMESYNC 或相邻遥测时间完成旧状态确认。

开发验证：dev-nav2-chain-5/6 原生路径、连续最终速度及取消均运行通过，
车辆控制帧 0，存在真实只读 TIMESYNC 帧；不是正式 A–I 或车辆导航验收。
源时钟/Writer 边界测试检查未知 nonce、未签名响应、RTT、UART 修正、长期
内存上界、实际帧序号、断连、传输失败和原 Writer 期限回归。原 10 ms 实验
配置在加密图启动负载下触发自身 20 ms cycle fence；保留该失败。20 ms 实验 profile 也可能在原生进程启动时触发 40 ms fence。
这些新实验没有作为验收基线；正式代码保留原 profile/watchdog 100/200 ms，
仅将调度显式设为 20 ms。既有配置、安全阈值及 200 ms 导航源期限没有调整。

ROS 控制器时间另使用公开 Gazebo Clock.system 的实际产生时间与同机
UTC/单调时钟对应关系，保留最多 2048 个 10 ms 锚点。迟到样本不更新水位；
超龄时拒绝新鲜度判断，真实新样本到达后可恢复。系统时钟跃变、世界回退
要求显式重建。它没有姿态真值入口，也不支持实机时间域；可信边界为本机
受信 owned Gazebo 部署，不能抵抗拥有宿主机/其他角色私钥的恶意进程。

本轮快速装配将可选查询最小间隔设为 20 ms，类的独立默认仍为 50 ms；
最多一个在途 nonce、200 ms RTT、64 个锚点及所有源时间判定均未改变。
查询后空闲循环不消耗控制优先级，下一条排队控制先获得一次尝试机会。
该标记不能越过 Deadline、Lease、Guard、Session 或 Generation。

Phase 5 Mission/Action 装配可选择 20 ms 调度等待，原应用默认仍为 50 ms。
这些改动尚未使静态绕障满足持续的 AP 200 ms 数据合同；最新开发失败必须
如实保留，不能因为增加查询或接收次数便声称数据必然新鲜。
