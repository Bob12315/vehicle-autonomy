# 目标二实现检查与验收约束

状态：2026-11-09 已按用户要求暂停并保存进度，目标二尚未整体通过。起点为目标一合并提交
`f3c97d0c7c626bacfc56157ea3193b53351418ad`；独立分支
`codex/mid360-goal2-wildthumper` 接续更换小车提交
`bd0bd33789eef27b2805f767a09cb36e89a0e231`。不连接实机，不合并或推送。

后续实际结果以最终验收报告为准。此前 L01 两车型各三次成功运行属于旧 Rover；
当前对 WildThumper 重新执行三次运动建图，旧车证据不转授给新车。
两车型回环、最新地图重定位及 48 项故障检查已有实际 PASS 记录；控制台回放
显示仍有 FAIL，最终版本重复实验、全量回归和交付审计待继续。L01 外围障碍物位于
原 ±5 m 控制围栏之外，因此增加独立 L02 内部立柱场完成绕柱测试，沿用完全
相同的数值误差/资源限值，在第一次 L02 运行前保存 acceptance-plan.json；
没有扩大 SafetyPolicy、修改原 L01 或用真值选择运行航点。

## 复用及边界

目标一已有 25 项原生验收、8 项控制台验收及 1054 项单元回归。
复用其模型副本装配、DomainLease、LocalTools/process_worker、原认证 UI、
RViz、rosbag 和退役工具清理。新三维能力不覆盖原均匀快照查看模式。

现有二维 SLAM Toolbox、MapExchange/MappingInput、地图锚点、只读 Nav2 规划
和 Rover FollowPath 继续保持原边界；三维点云不能冒充 OccupancyGrid。
冻结 LocalizationEstimate、WorldSnapshot、ResourceReference 和 TransformTree
均可承载带来源、时钟和 epoch 的只读三维状态，无需修改合同或 Core。
LIO 的 WorldModel 作为明确的只读来源提供，原 Driver/Action 采用的定位仍为
飞控报告位置，绝不把 LIO 注入 AP EKF 或原运动反馈。

## 时序修复和依赖

旧 720×28 点云是同一时刻快照，offset=0 是真实模拟语义，却不能用来验证
跨扫描运动去畸变。目标二单独启用审查后的 livox_gz_sim 切片后端：实际
Gazebo GPU 场景在每帧的五个时刻渲染，按记录扫描方向取样，保留每个切片
的真实采集时间。仍明确是离散切片近似，不能称连续激光精确模型。

上游 LivoxImu 输出 g，框架保持 m/s²，必须显式乘 9.80665；角速度保持
rad/s。实际 IMU 相对雷达原点为 (0.011, 0.02329, -0.04412) m，FAST-LIO
雷达到 IMU 的平移为其相反数。禁止软件“自动时间同步”猜测源时间。

第三方代码与构建放在仓库外，通过 HostEnvironment 索引。固定源码 commit、
许可证和补丁见 `simulation/dependencies/mid360-slam.lock.json`。只构建
Livox CustomMsg/CustomPoint 消息，不构建/启动 SDK 或物理雷达驱动。
Gazebo 插件补丁隔离每个实例的 ROS Context/Domain 和 use_sim_time，增加
原回调采集事件证据和有界 IMU 传输缓存，不改变射线几何、时间或配准算法。
FAST-LIO 补丁包含 Jazzy 构建、日志归属、有界订阅缓存与实际接收/保留的输入
时间诊断；不改估计、去畸变或配准数学。补丁边界见依赖记录。
FAST-LIO 的 LICENSE 为 GPL-2.0，不能按其 package.xml 的 BSD 标签省略声明。

## 定位与 TF 权属

FAST-LIO 只接收本实例的真实 CustomMsg、SI IMU 和仿真时钟。
Gazebo 真值 TF 继续在目标一的独立显示话题；LIO/地图/重定位工作进程
不得订阅该话题、Gazebo pose、飞控位置或测试裁判数据。
原始算法 TF 进入隔离话题，由唯一显示 Adapter 拥有正式 SLAM TF 链。
局部 LIO 原点不能被默认认定为全局地图原点；回环与重定位必须分别证明。
算法未可靠提供的速度/协方差明确为空或标注估计来源，不把默认零值当成
高精度状态。旧时间数据只查询对应采集时刻 TF，不使用 latest 代替。

异常输入、暂停/回退时钟、源重启、重复发布权、过期和跳变均需撤销有效
只读状态；重启产生新 generation/frame epoch，不能给旧数据刷新年龄。

## 地图和生命周期

累计地图来自 FAST-LIO 配准点云，按可配置体素滤波、空间范围和点数预算
管理。PCD 与独立元数据/校验值存于 RuntimePaths 持久地图目录，不属于包。
保存原始场景/会话、传感器与外参、算法/配置版本、frame epoch 和时间。
加载验证格式、大小、有限数、版本、校验和坐标约束。加载显示不代表定位。
停止 World 或后台要关闭当前/退役实例的 LIO、侧车、回放和 RViz。

## 独立验收

预先固定阈值见 `configs/mid360-slam-acceptance.json`。Rover/Copter 各三次
新仿真会话，运动只经原 Action/Execution/Safety/SITL 链。真值仅供独立
裁判，轨迹只允许初始一次刚体规约对齐，不能事后拟合全轨迹降低误差。
分别测量 ATE、RPE、姿态、返回漂移、几何、同步、延迟、CPU/RSS 和丢帧。
回环优化、PCD 加载、跨会话地图定位各用独立状态，不从局部 LIO 推定通过。
不兼容的成熟模块记录具体失败，不仓促自制重定位算法或宣称整套 PASS。
