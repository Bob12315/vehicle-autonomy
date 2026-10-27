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

23 的独立 World 目标误差约 0.192 m。实际 Writer 共 1,793 次：1,587 次只读
TIMESYNC、3 次 COMMAND_LONG、203 次局部 setpoint/stop。接触探针实际收到
203,169 组地面接触，障碍接触和未知实体均为 0。独立物理误差门槛 0.75 m、
停车 0.1 m/s 未改。环境清理记录为凭据已销毁、无残留进程组、端口已释放。
24 的实际物理目标误差约 0.291 m、停车约 0.0036 m/s，同样没有障碍接触。
两次场景的测试输入不同，不是两轮完整正式验收。

实际 TCP 小帧关闭 Nagle，与当前 ArduPilot TCP UART 一致；故障延迟仍由明确
注入参数控制。23 的 AP 位姿保守采样年龄（接收时的上界）P95 约 77 ms，
20 约 114 ms；这不是准确物理采样时间或硬件性能保证。

## 单元、安装和剩余验收

已完成的最新完整单元结果为 648 项通过；后续新增 Writer、原有资源冲突、
清理配置与 TCP 检查的定向测试通过；native-navigation-full-regression-6.log 为最新全量记录。原 P1 Writer 期限、
签名水位与回绕重放、ROS Service 不确定性、混合副作用及持久资源测试保留。
独立 wheel 开发检查 `dev-native-wheel-1` 通过，包含安装目录验证、默认无车辆、
未导入可选 ROS、安装 C++ 源码真实编译；最新冻结提交仍须重建。

| 强制组 | 当前状态 |
|---|---|
| A Provider | 元数据、安全身份和资源边界已有测试；完整装配/切换未完成 |
| B World/Sensor | 真实输入有开发证据；最终组合两轮未完成 |
| C SLAM | 真实建图/保存/加载定位有证据；最终生命周期/长期预算未完成 |
| D YOLO | 真实 World/Mission 事件有证据；最终组合复跑未完成 |
| E Nav2 | 单个空旷目标已通过；静态/动态障碍、无路、故障、取消等完整矩阵未完成 |
| F AP Native | 原能力保留；两轮三车型真实回归未完成 |
| G RViz/Web | DDS 只读权限正反对照已有；实际 RViz、浏览器闭环、新页面未完成 |
| H 性能/故障 | 有界流与源/写入边界已有；录制回放、统一诊断及长期全系统预算未完成 |
| I Phase 1–4 | 单元回归已有；两轮完整真实仿真回归未完成 |

尚缺：统一部署入口、可复用地图/感知 Action、完整 Provider 选择/恢复、Web
增量页面、真实 RViz 配置闭环、记录/安全回放、统一性能接口和硬件只读准备文档。
Copter/Plane 仍用既有 AP 原生控制；不宣称具有 Nav2 飞行或硬件/RKNN 支持。

## Git、输入与清理

既有阶段提交：c03b2c1、e658abd、4856ca1、8558bb9、9b6e03c、f1c054e。
本增量正式提交 SHA 与受测冻结输入将在提交后登记；不能以父提交代替新代码。
各运行 manifest 记录当时工作区是否有修改、源码摘要、SITL/插件/场景版本与
清理状态；旧失败没有覆盖。开发输入补充快照与正式运行前冻结应明确区分。

尚未完成全历史凭据/证据摘要复核。结束交付之前必须检查全部自有测试资源，
不触碰独立旧项目和用户文件，不输出认证密钥，不伪造已销毁二进制证据哈希。
最终只有全部强制项完成后才可改为 READY FOR RE-AUDIT，并等待独立审查。
