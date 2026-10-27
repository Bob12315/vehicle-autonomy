# Phase 5 开发记录与验收报告

状态：**FAIL（开发中；强制验收尚未全部完成）**。

本文持续记录实际开发，不是最终交付或独立 PASS 声明。不得用某个算法或
某个目标通过，替代两轮 A–I、Phase 1–4 回归或其余交付要求。没有进入 Phase 6，
没有开启实机运动。

## 基线与环境

冻结起点为 `34b72b57bab7a967de403c53839916a348aaf708`，原工作区干净，
基线单元测试 565 项通过。用户确认 Phase 4 已完成独立审查；没有伪造
额外审查文书。历史 FAIL、正式仿真和审查证据保持原样。

当前使用单独开发分支 `feat/phase5-world-navigation`。七模块结构保留。
完整 ROS 2 Jazzy 依赖从官方签名软件源提取到本项目独立 artifacts 前缀；
未升级系统 ROS，也未修改独立 ArduPilot 或 Gazebo 项目。实际软件版本：
Gazebo 8.15.0、Nav2 1.3.13、SLAM Toolbox 2.8.5、rclpy 7.1.12、rclcpp 28.1.22。
所有本轮车辆运行都是独立自有 Rover SITL/Gazebo 目录。

## Provider 与 World

算法能力目录与 P3 安全 ProviderRegistry 分开，选择算法不能授予 SEND。
原生导航安全身份使用实际 owned 仿真目录的 UID/device/inode 和 world epoch；
固定本机 ProviderRegistry、Ledger、资源定义与外部生命周期必须同时匹配。
导航与既有手动运动使用相同 `vehicle.control` 冲突组，Query 可以并行。
完整 Provider 生命周期管理、切换入口和 Web 页面仍未交付。

World 保存有界元数据和数据引用，图像/扫描/点云在独立有界双槽存储中。
每个样本保留来源、源时间、接收时间、时域、Frame/origin、generation/sequence、
标定、质量、协方差及摘要。撤下数据不清除旧序号水位。Replay/test truth 不能
作为导航依据。AP EKF、SLAM 估计与独立测试真值不混用。

## 实际传感器、SLAM、视觉

真实 Gazebo RGB/CameraInfo、2D LaserScan、3D PointCloud2 和 IMU 已进入
World；签名 AP 状态通过只读 API 转成 ENU/FLU Odometry/TF，没有第二个 Writer。
数据来源、安装外参、原时间和各自有效期单独验证。采集进程与车辆线程隔离。

SLAM Toolbox 原生建图、地图几何检查、原生 posegraph/data 保存、停止、重新加载
定位以及新 reader generation 已有真实开发证据 `dev-slam-7`。有已记录并单独
限定版本/哈希的原生边界兼容修补；不是用真值生成地图。正式长期建图预算、
可复用生命周期 Action 和新版组合的完整复跑尚待完成。

真实 YOLOX CPU 后端对 Gazebo 实际渲染图像推理，经 World 产生 object.detected、
object.lost、perception.degraded，并驱动既有 Mission 条件；证据
`dev-yolo-world-6`。图像级检测不伪造 3D 坐标。模型、输入图片、实现及事件
约束见 `phase5/YOLO_INTEGRATION.md`。更新后的完整装配还须复跑。

## 原生 Nav2 与车辆安全桥

使用原生 Planner、DWB Controller、Velocity Smoother、Collision Monitor、
BT Navigator，顺序为 raw → smoother → collision final。不直控 Gazebo 车轮。
最终数据属于一个既有 ActionRuntime 中的 NavigateToPose，复用 RoverStream、
Execution、Authority、Safety、唯一 MAVLink Writer 和原停车规则。

当前版本 rclpy 逐消息接口没有实际 publisher GID。小型只读 rclcpp 适配器使用
公开 MessageInfo，保留 GID、原始 stamp、完整 Twist 和实际接收时间；固定
164 字节 IPC 通过内核 PID/UID/start_ticks 校验。构建源码、ROS 包、DSO 和二进制
摘要另存。不复制规划/控制算法。

SROS2 Enforce 分角色限制原始、平滑、最终发布者和 Goal 客户端。逐命令绑定
Action、目标、Provider、会话、world/map epoch、Goal UUID 与实际最终 GID。
原始控制器证据独立于 Smoother 超时重打 stamp；200 ms 期限不能由接收续期。
扫描 300 ms、原生位姿/变换 500 ms、地图 10 s 的界限保持。

实际 Writer 临界区重新检查当前输入。关闭源与既有 Authority 锁同步：已进入
临界区的有界写入可先完成，关闭线性化之后不再放行该源。未确认停车或生产者
结束时保持 UNKNOWN/UNCONFIRMED 和资源占用。新的 ModeEffect 沿用原有 Rover
Drive 的 5 s 确认配置；运动源期限仍独立限制在 200 ms。

NativeNavigationJob 在任何原生进程/Goal 前完成 P3 登记。原生逻辑结果及时
交给车辆停车；全部登记进程组结束之后，才提供外部安全退出证明。原生结果、
独立新鲜 World 目标证明和停车均须成立。原生 StoppedGoalChecker 持续检查 XY，
位置/角度/停车阈值未放宽。准备 Goal 的结果未知时不重试；准备期禁止车辆 Effect。

## 开发验证与保留失败

证据根：`artifacts/phase5-world-navigation/`。以下均为开发场景，输入不同，
不能合并称为两轮正式 A–I。

| 证据 | 实际结果 |
|---|---|
| dev-nav2-secure-17/18/19 | 原生加密导航链、真实来源和新鲜零速；未装车辆桥，控制帧为 0 |
| dev-native-job-11 | 无运动桥；原生输出、同资源拒绝、取消后 cohort 清理、新合法 Goal |
| dev-native-motion-9/10 | 数据失效后停止；9 保持 UNKNOWN，10 安全退出为 FAILED |
| dev-native-motion-11 | Writer 拒绝过期运动指令；随后正常停车，测试 FAILED |
| dev-native-motion-12 | 接触探针 Topic 配置未生效，明确 FAILED |
| dev-native-motion-13 | 时钟查询暂停过宽使 Arm 退出缺少位置证据，UNKNOWN；接触探针已实际工作 |
| dev-native-motion-14 | 位姿证据失效，实际 Writer/Action 拒绝并停车 |
| dev-native-motion-15 | 原生返回成功，独立目标证明不足，应用拒绝成功 |
| dev-native-motion-16 | 首个实际运动缺少合法爬升起点，控制帧未发出 |
| dev-native-motion-17/19 | 逻辑结果与 DDS 退出传播/文件交接竞态，按失败处理 |
| dev-native-motion-18 | 写入时缺少有效原生位姿，实际拒绝并停车 |
| dev-native-motion-20 | 空旷目标开发场景通过；物理误差约 0.292 m，停车约 0.0045 m/s |
| dev-native-motion-21 | AP 证据超时；新 Action 遗漏既有 Mode TTL 配置，停车结果 UNKNOWN |
| dev-native-motion-22 | AP 证据超过 200 ms，停止并明确 FAILED |
| dev-native-motion-23 | 空旷目标开发场景通过；物理误差约 0.240 m，停车约 0.0044 m/s |
| dev-native-motion-24 | 认证 Web API 启动导航通过；手动控制 HTTP 409、Runtime 资源拒绝、并行 Query 成功、释放后正常模式控制成功 |
| dev-native-cancel-1 | 实际运动中 Web 取消，CANCELLED、安全释放、停车约 0.0006 m/s；确认关闭后无非零运动帧 |
| dev-native-bridge-loss-1 | 真实接收进程 SIGSTOP；源超时后 FAILED、零速写入及停车；冻结输入未变 |
| dev-native-controller-crash-1 | 真实控制器 SIGKILL；FAILED、停车、生产者组消失、安全释放；冻结输入未变 |
| dev-native-localization-loss-1 | 停止真实 SLAM 定位源；FAILED、零速写入及停车；冻结输入未变 |
| dev-native-no-path-1 | 原生控制器零速预备条件配置错误，明确失败；没有冒充无路测试成功 |
| dev-native-no-path-2 | 原生 Nav2 ABORT(6)，实际 Writer 无非零运动帧、物理位移不超过 0.05 m，安全退出 |
| dev-native-static-1/2 | 原生地图未覆盖目标；随后巡测原生 Goto 在墙边转向发生接触，分别保留失败 |
| dev-native-static-3 | 三个巡测点完成、原生图保存成功；定位激活因缺少订阅权限失败 |
| dev-native-static-4 | 保存和原生定位加载成功；Nav2 无可行路径，未发导航 Effect，绕障验收失败 |
| dev-native-lidar-loss-1 | 单独停止真实 LaserScan 桥，保留其他桥；FAILED、零速写入及停车；冻结输入未变 |

23 的独立 World 目标误差约 0.192 m。实际 Writer 共 1,793 次：1,587 次只读
TIMESYNC、3 次 COMMAND_LONG、203 次局部 setpoint/stop。接触探针实际收到
203,169 组地面接触，障碍接触和未知实体均为 0。独立物理误差门槛 0.75 m、
停车 0.1 m/s 未改。环境清理记录为凭据已销毁、无残留进程组、端口已释放。
24 的实际物理目标误差约 0.291 m、停车约 0.0036 m/s，同样没有障碍接触。
两次场景的测试输入不同，不是两轮完整正式验收。

实际 TCP 小帧关闭 Nagle，与当前 ArduPilot TCP UART 一致；故障延迟仍由明确
注入参数控制。23 的 AP 位姿保守采样年龄（接收时的上界）P95 约 77 ms，
20 约 114 ms；这不是准确物理采样时间或硬件性能保证。

真实外部回归 `real-external-regression-1` 通过：HTTP Job 重启（已知 ID 及
尚未收到 ID）、真实 ROS 2 Service 执行后丢失结果的 UNKNOWN/占用边界。
它不能替代剩余的全部外部、浏览器和车辆回归。

## 单元、安装和剩余验收

已完成的最新完整单元结果为 665 项通过（74.394 秒），记录为
`native-navigation-full-regression-9.log`。第 8 份全量失败日志独立保留。
新增地图文件、非授权通路、查询调度和周期维护边界测试均纳入全量。原 P1 Writer 期限、
签名水位与回绕重放、ROS Service 不确定性、混合副作用及持久资源测试保留。
独立 wheel 开发检查 `dev-native-wheel-1` 通过，包含安装目录验证、默认无车辆、
未导入可选 ROS、安装 C++ 源码真实编译；最新冻结提交仍须重建。

| 强制组 | 当前状态 |
|---|---|
| A Provider | 元数据、安全身份和资源边界已有测试；完整装配/切换未完成 |
| B World/Sensor | 真实输入有开发证据；最终组合两轮未完成 |
| C SLAM | 真实建图/保存/加载定位有证据；最终生命周期/长期预算未完成 |
| D YOLO | 真实 World/Mission 事件有证据；最终组合复跑未完成 |
| E Nav2 | 旧开发空旷目标、无路、取消和多种断流已有证据；当前静态绕障仍失败，正式完整矩阵未完成 |
| F AP Native | 原能力保留；两轮三车型真实回归未完成 |
| G RViz/Web | DDS 只读权限正反对照已有；实际 RViz、浏览器闭环、新页面未完成 |
| H 性能/故障 | 有界流与源/写入边界已有；录制回放、统一诊断及长期全系统预算未完成 |
| I Phase 1–4 | 单元回归已有；两轮完整真实仿真回归未完成 |

尚缺：统一部署入口、可复用地图/感知 Action、完整 Provider 选择/恢复、Web
增量页面、真实 RViz 配置闭环、记录/安全回放、统一性能接口和硬件只读准备文档。
Copter/Plane 仍用既有 AP 原生控制；不宣称具有 Nav2 飞行或硬件/RKNN 支持。

## Git、输入与清理

既有阶段提交：c03b2c1、e658abd、4856ca1、8558bb9、9b6e03c、f1c054e。
控制桥实现提交：`cd1774ef6bbd2e4c5d4027bb6c87a2adddb3b242`。
后续故障场景测试仍在开发，不能以该提交代表尚未完成的全阶段交付。
各运行 manifest 记录当时工作区是否有修改、源码摘要、SITL/插件/场景版本与
清理状态；旧失败没有覆盖。开发输入补充快照与正式运行前冻结应明确区分。

历史凭据审计发现旧 `operator-rover-20261026T095303Z` 遗留状态。已确认登记
进程组不存在、无其他活进程引用并取得 owner 锁，按原 device/inode 仅销毁
两项登记凭据资源中的四个文件。原 manifest 字节和审查/日志保持，新的
`historical-credential-cleanup/operator-rover-20261026T095303Z.json` 记录原 manifest
摘要、销毁前二进制摘要及 destroyed_unavailable；旧 EEPROM 不再可复核。
不宣称 SSD/COW/外部备份物理擦除。435 份更早的 EEPROM 没有签名验收元数据，
另有未登记旧状态，未解析密钥、未擅自收编或删除，审计结果单独保存。

全历史证据摘要复核仍待完成。结束交付之前必须检查全部自有测试资源，
不触碰独立旧项目和用户文件，不输出认证密钥，不伪造已销毁二进制证据哈希。
最终只有全部强制项完成后才可改为 READY FOR RE-AUDIT，并等待独立审查。

### 当前保存/加载定位的定向验证

原生定位激活需要 `/initialpose` 订阅，已在 SLAM 专用 Enforce 角色中补齐；所有角色仍没有该 Topic 的发布权，viewer/manager 也没有新增发布权。对应权限回归已通过。依据为 [SLAM Toolbox 2.8.5 原生定位生命周期](https://github.com/SteveMacenski/slam_toolbox/blob/2.8.5/src/slam_toolbox_localization.cpp)。

`dev-native-static-5` 曾验证独立保存/加载与绕障，但最终失败。巡测路径避开此前原生 Goto 的贴墙掉头；原生 Goto 不提供避障。仅本场景的建图处理间隔设为 0.4 秒，减少静止期间冗余图节点；加载后定位恢复原来的 0.1 秒处理间隔。World 新鲜度、足迹、Writer、停车、物理误差及运动安全阈值均未放宽。另用独立物理真值断言起点到目标的直线确实被保守车体边界阻挡，防止没有真实绕障需求的场景被误计成功。

`dev-native-static-5` 仍失败：原生全局规划有路径，但独立 CollisionMonitor 的 StopPolygon 在靠墙起点触发停止，控制器最终因无进展 ABORT；应用没有发导航运动帧。本轮地图文件约 16.3 MB，比上一轮约 55.2 MB 小。后续仅调整巡测结束位置，使初始车体转向空间离墙更远；不缩小 StopPolygon，不放宽控制器无进展时限。

`dev-native-static-6` 导航实际移动约 1.64 m、障碍接触为零，但实测车体运动超出保守扫描补偿上限，停车并 FAILED。后续仅收紧原生请求角速度/加速度至 0.2；实测 0.4 m/s、0.45 rad/s 保护上限不变。原生进展检查改用已安装的 PoseProgressChecker，以原生默认 0.5 rad 认可原地转向进展，原有平移半径 0.08 m、无进展 10 秒、总 Goal 期限、到达误差及停车判定不变。该语义变化明确记录，不能描述为所有算法参数完全未变。依据：[Nav2 1.3.13 PoseProgressChecker](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_controller/plugins/pose_progress_checker.cpp)。

`dev-native-static-7` 实际移动约 2.18 m、无障碍接触；实测角速度 -0.45514 rad/s 超过原有 0.45 上限，系统停车并 FAILED。后续保留 0.2 请求转速上限，仅进一步收紧原生请求角加速度至 0.05 rad/s²，避免快速转速变化引起飞控跟踪超调。目标朝向、到达条件和原有期限未变。

`dev-native-static-8` 未通过：控制器预备前的原生 Pose 超过 500 ms，尚未发送 FollowPath；该旧数据没有被刷新使用。修正为在原有 5 秒预备预算内等待真正新鲜的 Pose，而不是只等列表非空；仍不发送任何过期目标。保存图的定位配置关闭原生 loop closing，使用原生 localization 的匹配与有界定位缓冲；不改 SLAM 算法实现，不借 AP/Gazebo 真值伪造定位。

### 查询调度与 Guard 停顿的独立证据

`dev-native-static-9` 实际移动约 1.85 m 后命令到期，Writer 拒绝并停车。确定性复现 `native-query-priority-before.log` 证明：真实查询后经过一次空闲 owner 周期，新控制到来时被额外 TIMESYNC 抢先。修正只在发生实际控制尝试后清除查询优先标记，空闲不消耗；`native-query-priority-after.log` 的 15 项测试通过，核验真实帧类型、顺序、序号及 Writer 次数。未增加 TTL。

`dev-native-static-10` 实际移动约 1.53 m 后 Guard 超时并停车。`timing.json` 记录 53.95 ms 的 generation-2 GC 与该写前窗口重叠。新增可观测的周期前维护仅在可选 source-time-sync 快速装配运行，提前做即将到期的 full GC；不关闭自动 GC、不改变 GC 阈值、不修改 50 ms Guard 或任何有效期限。它是尽力的停顿管理，不是 Python 硬实时保证。维护耗时和次数随 driver info 输出。`native-maintenance-boundaries.log` 10 项通过，含维护跨过期限后 Writer 实际调用 0 次，以及随后有效命令正常发送。真实回归正在继续；没有把维护本身当成通过证据。

原生地图文件验证另覆盖路径越界、私有目录、所有者、软硬链接、空/缺失/超限文件、检查时截断；使用有界分块哈希，不把文件内容一次读入内存。`native-map-file-boundaries.log` 10 项相关测试通过。文件摘要不等于地图定位兼容性保证。

### 本轮当前结论：FAIL

`dev-native-static-11` 在约 2.00 m 实际运动后，AP 证据年龄约 217 ms 被拒；
`12` 冷启动最终零速通路未及时取得新鲜证据，未进入车辆运动；`13` 约 1.59 m
后 GC 停顿跨过源期限，Execution 返回 invalid_effect_time；`14` 采用更快调度后
仍在约 1.77 m 时出现 AP 证据年龄 206.93 ms，超过原有 200 ms，停车并 FAILED。
这些运行均保留原输入快照，未在运行中修改代码，14 障碍接触为零、车辆安全退出。
源期限、Writer Guard、停车及到达断言未放宽；没有将这些失败算作绕障通过。

独立只读 RViz 启动探针 `dev-rviz-readonly-1` 因缺少其私有 reset_time 服务权限
失败；补充仅该服务 reply 和点云订阅后，`dev-rviz-readonly-2` 在 Enforce 下实际
运行 10 秒并退出、销毁本探针登记凭据。该探针是无车辆的构造验证，不代表已
读取真实 SLAM/点云，也不是完整 G 组。没有新增 viewer Goal/运动发布权限。

全量回归第 8 份日志记录 665 项中的 7 个错误：旧测试直接构造 Driver 的内存
装配没有可选维护属性，新的诊断读取抛异常。已将可选诊断读取修为缺失时 None，
保留原测试与断言；后续全量结果单独记录，不覆盖该失败日志。

当前仍有关键 E 组失败，完整 A–I 两轮与全部真实旧阶段回归尚未完成，因此不能
给出 READY FOR RE-AUDIT。详见 `static-development-audit.json` 与各独立 run 目录。

## 用户暂停时的 Git 检查点（2026-10-27）

用户要求先暂停，再提交当前成果。本轮作为未完成 Phase 5 的开发检查点提交，
不代表全阶段完成或 READY FOR RE-AUDIT。当前结论仍为 **FAIL**：静态绕障存在
原有 200 ms AP 证据期限触发的失败，动态障碍、统一生产装配、Web/RViz 完整集成、
记录回放和两轮完整 A–I/旧阶段真实回归尚未完成。

最近全量单元为 `native-navigation-full-regression-9.log`：665 项、74.394 秒、OK。
最新代码真实空旷目标正向对照 `dev-native-reach-current-1` 通过：目标 (1.5, 0) m，
实际 (1.79198, -0.000094) m，距离误差约 0.292 m，停车约 0.00388 m/s；预备阶段
实际车辆控制 Writer 为 0 次。全程 2,794 次实际 Writer 中，2,541 次只读 TIMESYNC、
4 次 COMMAND_LONG、249 次 setpoint/stop；不能把查询统计成车辆控制。
运行输入冻结未变，车辆控制仍由既有安全链执行。

暂停后的只读清理检查覆盖本轮 14 个静态场景、2 个独立 RViz 启动探针和上述
空旷正向对照，共 17 个目录：登记临时凭据无残留；仿真剩余进程组为空、端口
释放已确认。历史证据未覆盖。当前代码与最新空旷运行的源码/测试/配置输入
快照一致；文档更新不属于执行输入。原始运行记录的 HEAD/dirty 状态保持原样，
不追改为提交后的状态。检查点提交可由本节所在 Git 提交准确定位。
