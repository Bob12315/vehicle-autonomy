# 仿真中心架构

本文件描述当前实现边界。实际通过数量以 `SIMULATION_TEST_REPORT.md` 和对应本轮原始日志为准，目录中的候选车型、历史 PASS 和 SDF 成功解析都不会自动授予更高验收等级。

## 资源、环境与控制

正式源码仍仅属于七个核心包；新增管理代码位于 `src/vehicle_autonomy/app/simulation/`，没有建立第二个 Vehicle 或 Mission 内核。

| 对象 | 实现及职责 |
|---|---|
| World | `scenarios.py` 生成独立 SDF 环境，`assets.py` 管理锁定上游资源；不包含任务逻辑或飞控命令 |
| Scene Registry | `catalog.py` 汇集 24 个编号配置、锁定上游 World 和历史 8 个入口；候选车型与实际可启动车型分开 |
| Vehicle | `vehicles.py` 与 `simulation/vehicles/catalog.json` 固定 Rover、Iris、Twin Cessna 版本与递归 SHA；World 不改变模型、参数或传感器。官方 QuadPlane 候选存在，Framework 专属准入仍阻塞 |
| Scenario | 编号、随机种子、经过白名单验证的参数、静态目标区及推荐测试；不等同相应导航/识别算法已实现 |
| Mission / Action | 仍由原 MissionControl、ActionRuntime 和注册表运行，仿真中心仅提供会话与唯一 target |
| Runtime | `universal_runtime.py` 为一个 World 启动一个 Gazebo，动态生成最多四辆固定车辆；各自复用 Session、签名证明和原 VehicleActionDriver，`runtime.py` 保留统计与旧接口 |
| Manager | `manager.py` 管理有界会话、状态机、结果、日志、资产任务和只读查询测试 |
| Web | 原登录会话/CSRF/Host/Origin/请求 ID 保护下的 `/simulation`；复用原 `/control` 和 Mission Studio |

控制路径保持：人工或 Mission → Action → Execution / Authority / Safety → Vehicle → MAVLink 唯一 Writer → 自有本机 SITL。管理器不提供车辆命令端口；`simulation.test` 只允许 `GetVehicleState` 查询。运动和 Mission 必须从原授权入口发起。部署 SEND 默认关闭，各 Action 的 SEND 仍需单独满足；硬件只读边界没有改变。

## 会话生命周期

正常转换为 `CREATED → PREPARING → STARTING → READY → RUNNING → STOPPING → FINISHED`。启动前取消为 `CANCELLED`；异常为 `FAILED`。创建时验证参数并生成可重放 SDF，启动时运行真实 `gz sdf -k`。实际 Gazebo 时间开始推进后才进入 READY / RUNNING；L2 要求继续观察到时间推进且没有必需资源/插件错误。SITL 启动和遥测出现不能将 L4 / L5 自动标为 PASS。

启动命令均为后端固定命令数组，浏览器不能指定 Shell、文件路径、二进制、System ID 或端口。每个 Gazebo 使用唯一 world 和 transport partition；SITL 从 40..100 范围选择独占实例，System ID 为实例号加一，并检查 TCP / FDM / 内部 UDP 端口。进程、模型、参数、签名凭据及 EEPROM 属于独立新目录。外部 ArduPilot、Gazebo 插件和 Twin Cessna 源目录只读使用。

停止先经原运行器取消该 target 的 Mission / Action，再执行 Driver 原有退出屏障，最后回收自有进程组和临时凭据。终止仿真进程不证明飞机已安全着陆；相关结果明确保留 `UNCONFIRMED`。已退役 Driver 保留在原运行器的 target 映射中以支持历史结果读取，不重用 target 身份。SITL 端口与自有组清理后才释放实例锁。

构造管理器不会启动进程或后台监控。后端重启后，未完成的会话标记 FAILED、所有权 UNKNOWN，不凭持久化 PID 自动接管或杀死进程，也不恢复 SEND 或旧 Action。操作员须查阅原会话证据。启动各原生阶段均有有限等待；管理器另检查启动总耗时。车辆需连接、拥有本次仿真身份，并提供新鲜 VALID pose / twist 才进入就绪。运行后连续 15 秒缺失统计、30 秒仿真时间停滞或实际 Driver fault / 断联会失败并清理。`failure_domain=framework` 保留已观察到的 World L2 PASS，不将框架故障误记为世界加载失败，也不会自动提升 L4/L5。资产下载任务有独立有界线程和取消检查，不阻塞 HTTP 处理锁。

## 暂停、重置与故障

无车世界的暂停、继续、重置调用实际 Gazebo WorldControl，并要求服务确认。已连接 SITL 的暂停/重置被拒绝：它会破坏现有严格时间和会话围栏，必须停止并创建新 epoch。不能以 UI 暂停状态冒充对飞控时钟的安全暂停。

`SoftwareFaultLink` 仅包装自有 Framework TCP 接收链路：有界接收延迟、确定性随机字节块丢失、原签名字节冻结重放、全遥测接收中断，以及写入前抛出命令超时。写请求不会为注入延迟而越过 Execution 检查后排队。冻结不修改原时间戳，旧签名仍由现有接收认证拒绝。故障恢复清空积压，不重新授予已撤销权限。

这些故障影响 Framework 的可见链路，不代表 SITL 的 GPS/IMU/气压计或 EKF 内部融合发生真实故障。没有相应受支持机制的扰动会被拒绝。World 的摩擦、几何碰撞、光照和动态目标属于实际 SDF；风环境字段是否影响具体 AP 机型动力学必须另做对照实验，不能从视觉效果推断。

## 证据与性能

每会话保存 `report.json`、`samples.jsonl`、`sdf-check.log`、`gazebo.log` 及可用时的 `sitl.log`。记录配置版本、有效参数、种子和生成 SDF 的 SHA256。Ground Truth 直接读取独立 Gazebo pose/info，飞控估计来自 Driver 的不可变 WorldSnapshot，保留来源和时间，不互相冒充。

指标包括真实统计中的仿真秒、RTF、实际进程组 CPU 采样和 RSS、首次可观察就绪耗时。GPU、碰撞事件、未配置摄像头、外部传感器、未运行任务都保持未知。会话 API 只返回最新采样，完整报告和 JSONL 保留历史；性能比较要求相同场景、车型、种子和参数，不能据此提升验收等级。

上游锁定条目、下载状态、许可证与缺失依赖见 `GAZEBO_SCENE_CATALOG.md`；大型下载、缓存、日志和构建不提交 Git。RViz2 继续负责专业空间可视化，本轮没有增加另一套导航地图或 LLM 决策链。

## 通用车辆组合与受控切换（2026-10-29）

`world_spawns.py` 从独立的 `world_spawns.json` 读取可审查的出生区域，再检查实际生成
几何、支撑面、跑道与相邻车包络。当前 Rover/Copter 各 22 个 World、Plane 6 个 World
通过静态准入；这些数量不表示已完成原生运动验收。未审查的上游网格、R05/C06 动态
碰撞包络、Plane F05/F07 被明确阻塞。原生与 Web 结果见
[通用组合测试报告](UNIVERSAL_SIMULATION_TEST_REPORT.md)。

每个 VehicleInstance 有新 target、实体名、SITL 进程、System ID、TCP/FDM/内部 UDP、
签名凭据、接收水位和 Driver 会话；共享 Gazebo 只作为各子证明的只读存活依赖。
子 Session 的自有进程列表只有其 SITL，不会结束其他车辆或共享 World。实体生成、
真实 JSON 插件连接、SITL listener、独立 Gazebo pose 与 Framework 新鲜状态分别记录。
JSON 插件连接证据来自该实例 SITL 日志的 `JSON received:`，不是配置完成提示。

正常单车移除先取消该 target 的任务、通过原退出屏障，并要求新鲜且已上锁、静止地面
状态。关闭 Driver 后仍保持 SITL FDM 运行；删除实体，独立观察其从 pose 流消失，
再结束该 SITL、销毁凭据、确认自有组结束并释放端口锁。Gazebo 的 remove ACK 只是
排队确认，不能替代实体退役观察。意外 SITL 故障可能卡住 lockstep World，此时整个
World 失败并清理，不能宣称具有任意进程崩溃后的物理隔离。

动态添加暂时屏障所有已有 target 的新控制准入，要求同伴均为安全静止地面状态，
并重新读取实际 Gazebo 位置检查间距；不能只信初始出生点。新增失败在本地回滚，
无法确认实体清理时保留所有权并退役 World。持久化错误不会抑制独立进程清理。

World 切换先准备并验证新配置，再屏障旧 target、取消任务并检查所有历史安全障碍
（不使用展示列表的 64 条截断）。所有车辆均须已上锁、地面静止；空中或未确认退出
明确失败，须通过原控制页完成返航/降落/上锁。旧 World 完整退役后才启动新 World。
固定版本、fingerprint、参数和传感器 SHA 保留，target、签名、session/generation 全部更新，
SEND 不继承。`switch` 状态明确区分 PREPARING/STOPPING/STARTING/SUCCEEDED/FAILED。

退休屏障同时位于 Web 准入与 Driver owner 线程的 open_scope 内；允许原安全退出，
拒绝新任务或接管竞态。已关闭 Driver 仅保留历史结果读取，在线车辆选择隐藏旧 target。
无车暂停/重置保留；带 SITL 的原地重置继续拒绝。

所有通用实例固定使用已有签名 TIMESYNC 与 20ms owner 周期，并通过公开只读
参数回读证明 SERIAL0_BAUD=115；所有 TTL/3秒新鲜度/200ms周期屏障保持原值。
Plane 原生 continuation 内的就绪循环也使用已配置的 20ms owner 周期，避免在该阶段
退回 100ms 查询而耗尽原有准入期限；模式/着陆/UNCONFIRMED 语义与全部安全阈值不变。
该时钟策略对所有 World 一致，三张目标地图均另跑完整固定翼航线验收。

历史摘要只保留姿态、运动、健康与阶段；完整原始采样另存 JSONL，避免反复序列化
大量重复遥测跨越控制周期预算。摄像头、气压计/磁力计等未运行的数据管线仍标
NOT_TESTED；保留固定模型中的传感器配置不等于这些管线已激活或感知算法已验收。

控制 owner 进一步隔离在每车自有的 `framework-worker` 进程。受信父进程经继承的私有
文件描述符传递 ActionDriver 的 typed 请求和不可变状态，worker 内仍构造原
OwnedActionSimulation、VehicleActionDriver、Execution、Safety、Authority 与唯一 Writer。
签名私钥只由实际 worker 内的原证明读取；父进程只有公开身份/统计投影，存活断言
由实际证明执行。没有新网络监听或公开原始 MAVLink 接口。IPC 请求上限 128，断链
会失败全部未完成 Future、撤去界面存活/SEND 显示；真实执行侧仍独立检查 TTL 与退出。
进程组由相应 Vehicle Session 注册和回收，不能被借用的 World 证明当作自有关闭目标。
这消除了 Web/报告/资源装配的 Python GC 对该车辆安全循环的阻塞，不改变 GC 全局设置。

出生点除 World 几何外还须在原 Framework profile 的 geofence 内；例如 Rover/Copter
的 north-far/south-far 虽有物理地面空间，超出原 ±5m 控制范围时不能启动。新增 east/west
预设使四车默认布置不需要扩大安全围栏。目前非 Plane 仍使用已验证的固定 ENU 地理
原点；不同地理原点或旋转坐标系须另行提供合格的 Environment 绑定，不能只修改地图
元数据后推断控制兼容。World 与 Vehicle 分离不等于任意外部地图已通过准入。
