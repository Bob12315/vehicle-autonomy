# 仿真中心架构

本文件描述当前实现边界。实际通过数量以 `SIMULATION_TEST_REPORT.md` 和对应本轮原始日志为准，目录中的候选车型、历史 PASS 和 SDF 成功解析都不会自动授予更高验收等级。

## 资源、环境与控制

正式源码仍仅属于七个核心包；新增管理代码位于 `src/vehicle_autonomy/app/simulation/`，没有建立第二个 Vehicle 或 Mission 内核。

| 对象 | 实现及职责 |
|---|---|
| World | `scenarios.py` 生成独立 SDF 环境，`assets.py` 管理锁定上游资源；不包含任务逻辑或飞控命令 |
| Scene Registry | `catalog.py` 汇集 24 个编号配置、锁定上游 World 和历史 8 个入口；候选车型与实际可启动车型分开 |
| Vehicle | 代表性 R01 / C01 / F01 复用现有 Rover、Iris、Twin Cessna 模型和参数；VTOL 没有合格 profile，明确阻塞 |
| Scenario | 编号、随机种子、经过白名单验证的参数、静态目标区及推荐测试；不等同相应导航/识别算法已实现 |
| Mission / Action | 仍由原 MissionControl、ActionRuntime 和注册表运行，仿真中心仅提供会话与唯一 target |
| Runtime | `runtime.py` 复用 `qgc_simulation.Session` 的进程管理、FreshSimulationSigning 和 `OwnedActionSimulation`，组装现有 `VehicleActionDriver` |
| Manager | `manager.py` 管理有界会话、状态机、结果、日志、资产任务和只读查询测试 |
| Web | 原登录会话/CSRF/Host/Origin/请求 ID 保护下的 `/simulation`；复用原 `/control` 和 Mission Studio |

控制路径保持：人工或 Mission → Action → Execution / Authority / Safety → Vehicle → MAVLink 唯一 Writer → 自有本机 SITL。管理器不提供车辆命令端口；`simulation.test` 只允许 `GetVehicleState` 查询。运动和 Mission 必须从原授权入口发起。部署 SEND 默认关闭，各 Action 的 SEND 仍需单独满足；硬件只读边界没有改变。

## 会话生命周期

正常转换为 `CREATED → PREPARING → STARTING → READY → RUNNING → STOPPING → FINISHED`。启动前取消为 `CANCELLED`；异常为 `FAILED`。创建时验证参数并生成可重放 SDF，启动时运行真实 `gz sdf -k`。实际 Gazebo 时间开始推进后才进入 READY / RUNNING；L2 要求继续观察到时间推进且没有必需资源/插件错误。SITL 启动和遥测出现不能将 L4 / L5 自动标为 PASS。

启动命令均为后端固定命令数组，浏览器不能指定 Shell、文件路径、二进制、System ID 或端口。每个 Gazebo 使用唯一 world 和 transport partition；SITL 从 40..71 范围选择独占实例，System ID 为实例号加一，并检查 TCP / FDM / 内部 UDP 端口。进程、模型、参数、签名凭据及 EEPROM 属于独立新目录。外部 ArduPilot、Gazebo 插件和 Twin Cessna 源目录只读使用。

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
