# 原生导航来源与退出合同（开发阶段）

受测环境的 rclpy 7.1.12 的逐消息字典只有 source/received timestamp 和
publication/reception sequence，不能据此得到 publisher GID；节点图的
GID 不能冒充逐报文来源证明。依据：
[rclpy 7.1.12 官方 subscription.cpp](https://raw.githubusercontent.com/ros2/rclpy/7.1.12/rclpy/src/rclpy/subscription.cpp)。

因此新增只读、独立编译的小型 rclcpp 接收适配器。它使用公开
MessageInfo.get_rmw_message_info().publisher_gid，保留原始 TwistStamped
stamp、完整六轴 Twist、frame 和实际 CLOCK_MONOTONIC 接收时刻；不修改
ROS 2 内部库，不链接 MAVLink，不持有车辆端口。经私有 Unix datagram 传递
固定 164 字节帧；内核 SCM_CREDENTIALS、UID、PID/start_ticks、格式、大小
和有界 drain 均由 Python 消费端验证。排队/延迟不能更新原始证据时间。
源码、二进制、ROS 包版本和 runtime DSO 哈希由独立构建工具记录。

原生管理客户端在 SROS2 Enforce 下，仅接纳自己这次 cohort 的来源：
PREPARING 阶段为 Wait 行为，ACTIVE 阶段为 Controller；最终来源必须是
Collision Monitor 的唯一真实 GID。三节点输出链仍由原生 Nav2 完成，
原始控制器证据独立于 Smoother 超时重打 stamp；200 ms 源期限不变。
新的原生 BT 由 ComputePathToPose / FollowPath 原生插件构成；不准许一个
独立 Spin/BackUp 恢复输出流绕过该宏的来源约束。不是自写规划/局部控制。

NativeNavigationJob 在任何原生进程/Goal 产生前注册到现有 P3 生命周期。
持久化 provider/resource 身份由实际 owned 仿真目录 device/inode 绑定；
UI 名称、Action UUID、scope 和替代目录不产生第二个协调身份。
Runtime 仍是原来的一个 Runtime，车辆仍需双 SEND、Lease、Safety 与唯一
Writer。数据桥只产生既有 RoverStream 的 Typed Effect，每次沿用原始
源期限及最早传感器/AP 证据期限。实际写入临界区还重新核对当前证据。

Nav2 Goal 的逻辑终态本身不是外部退出证明。当前实现为每次宏启动有界、
受控的原生进程 cohort；退出时验证全部登记的 Goal/Controller/Smoother/
Collision 等进程组结束后，才提供外部安全终态。车辆的 StopMotion/HOLD、
8 秒退出、0.1 m/s 和 2 秒稳定停车仍是另一个独立证明，全部成立才释放。
进程 PID 消失不能独自证明安全；丢失/破损持久记录或残留进程组保留 UNKNOWN。

本轮开发证据 dev-native-job-11：真实 ROS/SITL/Gazebo 下取得实际来源 GID
的非零输出，同资源竞争拒绝；取消后整个 cohort 结束并释放资源；随后同一
物理仿真新 Goal 正常 SUCCEEDED。未装运动桥的该测试车辆控制帧为 0。
该记录不是完整 Phase 5 A–I 或真实导航通过声明。

部署边界是受信同机、独占 owned SITL、受保护的 SROS2 凭据和持久化根目录。
不声称防御能够读取其他角色私钥的宿主机进程，不声称跨独立主机全局协调。
Rover 运动桥仍在开发验证，Plane/Copter 继续使用原有原生 AP 能力。


实际运动开发检查 dev-native-motion-20 与 23 已通过各自空旷目标场景。
23 的物理目标误差约 0.240 m，停车约 0.0044 m/s，无障碍接触；不是两轮完整
A–I。当前桥关闭与既有 Authority 锁统一；实际 Writer 拒绝测试和正常对照均有。
Typed Effect 的运动资源使用与既有 Rover Drive 相同的 vehicle.control 冲突组，
ModeEffect 也沿用其已验收的确认配置，不能用新 Action 默认值缩短确认链。
源时间、取消/外部责任和未解决事项见主报告。
