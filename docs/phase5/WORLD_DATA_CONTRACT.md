# Phase 5 World 数据合同（已实现部分）

正式模块为 `contracts.streams`、`world.model.streams`、`world.model.stream_input` 和
`world.sensors.ros2_streams`。这些数据接口不持有车辆 CommandPort，不授予 SEND。

每条引用保留 source/sensor、类型、源时钟时间、映射的采集时间、本机接收时间、
frame/单位/高度基准、来源类别、generation/sequence、标定版本、质量、置信度和协方差。
接收新消息不能延长旧采集数据的有效期。重复、乱序、跨 generation、错误时域和未来时间
不能通过导航输入检查。回放和 Gazebo 真值可显示，但 `StreamState.require` 拒绝将其
作为导航定位或感知证据。坐标转换沿用已有 ENU/FLU 与 NED/FRD 合同。

WorldSnapshot 保存不可变的当前有效引用。原始图像、扫描、CDR PointCloud2 和 IMU
保存在私有目录的固定槽中：默认 8 槽、每槽最多 8 MiB；每种输入预留两槽，防止高频 IMU
覆盖相机。读取校验所有者、文件类型、大小和 SHA-256，旧槽被替换后引用失效。
World 中已有三维对象保留容量限制及过期清理，像素框不能被当作三维位置。

ROS 2 worker 使用真实 Gazebo RGB、CameraInfo、LaserScan、PointCloud2 和 IMU。
AP Odometry 只来自原有签名接收链已经验证且有效的 AP 估计，不使用 Gazebo 真值。
保持原始采样时间，用已观测到的 ROS/host 时钟插值，不外推。插值与接收的微小时序不确定性使用更早的保守上界，保留原源时间，不能借接收刷新旧采集。扫描必须得到同采集时间的
`odom -> laser` TF 后才转发。AP 原有 IMU 带 FRD 安装旋转，保留其 frame 并发布显式外参，
不将原始数值误标为 FLU。相机内参来自真实 CameraInfo；默认话题是图像话题父级的
`camera_info`，不是在图像话题下继续拼接。

高频原始 ROS Topic 不修改；World 引用处理的 IMU 输入最多 100 Hz、其余按有界队列
处理。扫描队列 8，其他输入队列 2；超过容量丢帧并计数，年龄上限仍为 500 ms。
固定数量的当前引用及计数器不保存无限历史。WorkerStreamInput 在独立采集线程中解析
原子状态文件，一批样本全部验证后才更新。故障撤回引用但不重置序号水位；恢复必须使用
合法的新帧。generation/原点或 worker epoch 变化需要重新装配，不能默默沿用旧身份。

新增只读 `/api/world/vehicle` 入口沿用现有 Web Bearer 认证，用于提供 AP 原始已认证
状态。StreamCollector 得到的窄接口仅允许注册、摄入和撤回流，无法改写 AP 状态或权限。
原始字节读取、ROS 和文件解析都不进入 MAVLink/Safety owner 周期。

## 当前真实开发证据

`artifacts/phase5-world-navigation/dev-sensors-6/summary.json`：真实 Rover SITL + Gazebo，
四种传感器引用进入同一个 WorldSnapshot，CameraInfo 有效，扫描持续配对，实际车辆 Writer
写入 0。`stage2-unit-commit.log`：584 项全量单元测试通过。`dev-sensors-7` 另验证 IMU 有界降采样；原始 ROS Topic 未改变。`stage2-unit-final-584.log` 为该增量最终全量运行。
这些属于开发边界验证，不是两轮 Phase 5 A–I 正式验收。

保留了失败探索记录：dev-sensors-1 修改 IMU Topic 后插件无法取得 JSON 数据；修复仅在自有
生成 SDF 中撤销该修改，没有改独立插件。dev-sensors-2 的弱通过不能代表完整通过；
dev-sensors-3 暴露 AP 参数回读与真实消息周期不同。当前仿真预配置在 Action owner 启动前，
通过公开 PARAM/SET_MESSAGE_INTERVAL 接口配置并实际验证三种位姿消息的 100 ms 周期。
它只用于自有 Rover 仿真启动，不在运行中的车辆链增加 Writer，也不启用硬件控制。

当前 ROS 2 数据边界依赖受信本机部署和私有文件权限，不声称 DDS namespace 或 Domain
能够提供强认证。后续导航桥仍必须独立验证 Action/Provider/目标/Session/generation、源时效
及最终控制源，再由既有 Authority、Safety、Execution、唯一 Writer 执行。
