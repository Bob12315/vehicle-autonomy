# Phase 4 — Mission Graph 与三车型控制中心

**READY FOR RE-AUDIT**。开发侧完整测试已通过，等待独立审查；本报告不宣布 Phase 4 最终验收 PASS。
范围仅为明确自有的本机 SITL/Gazebo。没有连接实车，没有进入 Phase 5。

## 1. 基线、提交与证据

- 分支：`feat/phase4-mission-control`。
- 起点：`e4a0b86f6cd30437beca49c0d402a9129468bb94`。
- Phase 3 冻结标签实际指向：`43d849fef21bc432eff536a00da43fb13a8c0e25`。
  实际文书为用户授权的受信本机仿真冻结，没有找到新的独立 PASS 文书；此前三轮独立 FAIL 保留，未冒充独立通过。
- 实现提交：`23f9dd84a31cd34989095aab0182ec6c9f740a1b`。
- 最终受测提交：`3c29d39504c227fd7505b1e500743c36c24bacb9`，只在上一提交上修正新增测试的异步退出观察并记录首个正式 FAIL，生产代码未改变。
- 正式运行：`artifacts/phase4-mission/acceptance-3c29d39-1/`，UTC 2026-10-25T23:50:17.482688+00:00 至 2026-10-26T01:58:45.907081+00:00。
- 原始文件索引：[evidence.json](phase4/evidence.json)，2037 个现存证据文件、1,851,651,827 字节，包含开发失败、首个正式 FAIL 与最终完整运行。
  索引 SHA-256：`c6a9a051f4b9fa2e2e5ec54a573e083bed73a94554142633eded913bd0af8570`。
- `frozen-inputs.json` 固定 596 个跟踪文件，包含生产源码、测试、CI、文档和二进制仿真模型资源，另记录三车型 SITL 二进制摘要。
  前后全部一致。最终附加核验还确认 13 个实际二进制、插件和参数输入文件未变。
- 生产/测试/脚本/配置/仿真输入的前后聚合 SHA-256：`018af3567867766a2eb0ba29d4e720da40633e17afd9668fa8f76191a78f5716`。
  旧 Phase 2 入口使用不同聚合规则，其前后也一致，不能把两种算法的摘要混用。

本报告及索引为受测实现之后的文档提交；冻结输入中的报告是当时的开发记录，最终说明不伪造该旧哈希。
详细 Schema、部署前提和操作方式见 [合同与使用说明](phase4/CONTRACT_AND_USAGE.md)。

## 2. Mission 合同与运行时

`contracts/mission.py` 定义不可变 MissionSpec、BlackboardValue、三值 Truth、只读 WorldSnapshotProvider/EventSource。
`engine/mission/graph.py` 在运行前校验 Schema、节点参数、能力、车型、版本、资源及连接。
Mission ID/版本、run ID、node execution ID 与 Action ID 独立；发布的版本不可覆盖，运行中的图不会随草稿变化。
JSON 可以保存、加载、导入、导出，Action 引用锁定 Registry 精确版本。

图采用有序有根树，拒绝环、共享可变节点、孤儿、未知字段和不支持的车型；重复由显式 Repeat 表达。
最多 128 节点、深度 16、每复合节点 32 子节点、Repeat 20 次、每任务 256 Action，总期限最多 1800 秒。

| 节点 | 服务端语义 |
|---|---|
| Action | 提交给同一个 ActionRuntime，分别观察逻辑结果与安全退出证据 |
| Sequence | 按连接顺序推进，UNKNOWN 不继续普通运动 |
| Parallel | all/any/main 完成策略与 fail_fast/all_failed 失败策略；结束前清理其余活动子项 |
| Condition | 类型化 TRUE/FALSE/UNKNOWN；UNKNOWN 分支仅允许查询/等待 |
| Fallback / Recovery | 只有确定失败且安全退出后进入备选，UNKNOWN 不当作普通 FAILED |
| Event / Reactive | 事件身份去重、消费水位、TTL；Reactive 先可信退出 main 再启动响应 |
| Wait / Timeout / Repeat | 有界等待、独立节点期限和有限重复，每次执行使用新身份 |

`graph_runtime.py` 负责节点、Action 关联、Blackboard、取消、超时和历史；只通过 ActionRuntime 产生副作用。
`journal.py` 复用原 DurableRecord 的短写检测、校验、原子替换及文件/目录 fsync，并加目录 anchor 与 lifetime flock。
意图在 Action 回调执行前持久提交。存储失败关闭新入口，但继续独立安全退出 tick。

## 3. World、Blackboard 与事件边界

`world/model/mission_inputs.py` 不开发感知融合。查询使用 AP 已有状态、Action 输出及明确注入的确定性事件。
支持 eq/ne/lt/le/gt/ge/all/any/not，不使用 eval，不把布尔与数字混用。
缺失、过期、未来时间、错时域、低质量或 frame 不匹配均 UNKNOWN。

Blackboard 保留最初 result_at，嵌套 World/Stamped 保留原始采样、发布时间与质量；不能用新的外层结果时间刷新旧观测。
类型化参数绑定先验证来源/期限/frame，再通过原 Registry 参数 Schema；未获得有效数据时有界等待后保持 UNKNOWN。
无隐式坐标变换，offset 使用字段声明单位。

LocalEvents 有身份和数量预算，不逐出旧 ID 使重放重新有效；订阅前、重复或过期事件不会触发新运动。
两轮真实车辆应用均执行了完整逻辑矩阵，逻辑/查询图实际 Writer 为零。
没有把这些测试称为 Camera、YOLO、LiDAR、SLAM、地图融合或 AI 已实现。

## 4. Mission Studio 与三车型手动控制

`vehicle-autonomy-missions` 提供 `/studio`、`/control`，`/` 保留原 Action Lab。
复用原 loopback、私密 Bearer、CSRF、Host/Origin、请求限额和幂等 ID；默认无车辆、双 SEND 关闭。
只有明确的 owned manifest 才可装配车辆，首次部署 Registry 初始化必须显式指定，既有根不能重置。

Studio 支持节点库、拖拽、连接/删除、属性、Registry 动态参数、车型/能力过滤、验证、撤销/重做、
布局/缩放/导航、版本保存/加载、JSON 导入导出、启动/取消、实际节点高亮、反馈及有界历史回放。
前端不调度 Mission。真实 Chrome 两轮均通过界面创建、保存、导入导出并运行三车型图。

| 车型 | 操作台能力 |
|---|---|
| Rover | Arm/Disarm、GUIDED/HOLD、前后/转向/速度、地图 Goto、Stop、RTL、按住键盘或虚拟按键 |
| Copter | Arm/Disarm、Takeoff/Goto、平移/升降/航向、Hold/RTL/Land、连续键盘或虚拟按键 |
| Plane | 地面安全 Arm/Disarm、原生 Takeoff/SetGuidedTarget、地图目标、Loiter/RTL/AutoLand |

显示连接、签名计数与新鲜度、SEND、Armed、模式、位置/速度/姿态/航向/高度、航迹、任务、资源、错误和日志。
Rover/Copter 使用 AP odom ENU；Plane 地图使用 WGS84 经纬度和 AMSL。Gazebo 真值只作独立验收，不进入控制。
Plane 无 RC override、舵面直控或零速停车；空中 Disarm 实际被拒绝且 Writer 为零。
目标配置和 RTL 确认不表示物理抵达或降落。

连续输入更新同一个原 Continuous Action：同会话、递增序号、一次性期限票据、20 Hz 上限、原参数限幅、
0.4 秒服务器 deadman，UI 10 Hz。票据用十进制字符串避免 JS 大整数精度丢失。
Effect 截断到输入期限，输入不能延长 Action 最大寿命或复活过期会话。松键、失焦、隐藏、退出和断网停止更新，
恢复必须重新授权；停止未确认则保持 UNKNOWN/UNCONFIRMED。

## 5. 资源、控制权与重启

MissionGroups 直接使用原 ActionResources，不另建车辆 Authority。任务在子 Action 之间保留资源，
子项只持有不可序列化的进程内成员许可，仍受原 Lease/TTL、Session/Generation、双 SEND、Safety 和唯一 Writer 检查。
伪造成员身份、超出预留资源、原 Action Lab/raw Runtime 插入，以及运行中盗取旧 continuation 均被拒绝。

手动接管只请求可信退出，不授予权限；取消窗口、UNKNOWN 与未知外部作业阻止新普通运动。
Plane 成功保留的 native flight 可以显式交接；资源转交与物理停止分别记录。

实际 owned SITL epoch 通过现有固定 OS ProviderRegistry 绑定到唯一 Mission Journal/target。
同目录或不同目录、相同或不同别名的第二个 owner 在副作用前拒绝，失败装配不关闭已有 Driver。
重启保留 UNKNOWN 与资源阻挡，不重建旧 Action、输入、Lease 或 SEND。
受控重建要求认证的新鲜静止未解锁地面状态及同一 owned identity；更换仿真还要求旧 SITL/Gazebo 完整退出与凭据清理证据。
独立 HTTP/ROS/Native Job 责任必须另有原 Provider 可信对账，车辆地面状态不能解除它。

两轮 Rover/Copter 的只读重连和受控重建实际 Writer 都为零；之后新授权的 Mode/Arm/Disarm 每例实际写入 3 帧，证明正常控制没有被永久拒绝。
旧 UNKNOWN 历史仍为 UNKNOWN，仅在充分证据后解除资源阻挡。

## 6. 两轮正式 A–J 结果

正式入口：

```bash
./scripts/test_phase4_missions.sh --allow-send \
  --sitl-bin-dir artifacts/phase2-control/ardupilot-source/build/sitl/bin \
  --run-dir artifacts/phase4-mission/acceptance-UNIQUE
```

| 组 | 覆盖 | 第一轮 | 第二轮 |
|---|---|---|---|
| A | Schema、连接、版本、参数、车型、资源拒绝 | 通过 | 通过 |
| B | 全节点、取消、超时、安全恢复 | 通过 | 通过 |
| C | Rover Arm/Goto/条件/ReturnHome/Disarm 真值 | 通过 | 通过 |
| D | Copter Takeoff/Goto/ReturnHome 真值 | 通过 | 通过 |
| E | Plane 起飞/目标/Loiter/RTL/AutoLand 真值 | 通过 | 通过 |
| F | Chrome 三车型手动控制、deadman、断线、Writer | 通过 | 通过 |
| G | Chrome 创建/保存/导入导出/运行/状态闭环 | 通过 | 通过 |
| H | 冲突、接管、UNKNOWN、重启、Plane 续飞、HTTP 混合作业 | 通过 | 通过 |
| I | 三值条件、事件新鲜度/去重/订阅边界 | 通过 | 通过 |
| J | 原 Phase 1/2/3 完整两轮回归 | 通过 | 通过 |

新场景目录分别为 `round-1-5037294a/`、`round-2-9c59760e/`，每例使用全新状态和认证材料，物理场景串行。
原始证据包括输入图、实际 Runtime/Writer、应用接收、代理转发/丢弃/重放、Gazebo 轨迹、截图、清理 manifest 和时限观测。
六次 Chrome 三车型场景的 JavaScript error 列表为空。

| Mission 真值 | 第一轮 | 第二轮 | 原门槛 |
|---|---:|---:|---|
| Rover Goto 误差 m | 0.1913 | 0.1917 | ≤0.75 |
| Rover 返航误差 m | 0.6766 | 0.7232 | ≤0.75 |
| Rover 返航停止速度 m/s | 0.0039 | 0.0094 | ≤0.1 |
| Copter Goto 误差 m | 0.1718 | 0.1705 | ≤0.75 |
| Copter 返航误差 m | 0.0031 | 0.0034 | ≤0.75 |
| Copter 停止速度 m/s | 0 | 0 | ≤0.15 |
| Plane 起飞相对高度 m | 51.636 | 51.637 | 50±5 |
| Plane 目标中心误差 m | 83.508 | 83.665 | ≤120，另需稳定3秒/累计转弯≥π/2 |
| Plane 任务落点误差 m | 1.444 | 1.326 | ≤80，横向≤15 |
| Plane 手动最终速度 m/s | 0.531 | 0.590 | <1，另需可信接地/解锁 |

Rover/Copter 各轮松键为 CANCELLED，输入过期和断线为 TIMED_OUT，均有真值停止证据，过期非零运动实际写入均为 0。
两轮 Plane 边界均观察 16 次 packet sequence 回绕，真实丢弃新 ACK 1 帧、转发/应用接收均为 0；
旧签名 ACK/HEARTBEAT 各被拒绝，状态不回退，不确定任务保持 UNKNOWN，普通新接管 Writer 为 0。

混合 HTTP 测试每轮覆盖退出异常与超时：真实外部作业仍 RUNNING 时车辆 Driver 独立 release_safe，
共同资源仍占用，fallback 不创建第二作业。原作业可信终态后新正向任务成功；每例总共 2 个实际 Job，
负例车辆写入分别为 0/1，冲突拒绝新增 Writer 均为 0。没有用全部拒绝或永久锁死获得通过。

## 7. 单元、既有回归与安装

基线 512 项保留，新增 53 项确定性/HTTP边界测试，最终全量 565 项，0 失败、0 错误、0 跳过。
正式入口、原 Phase 3、原 Phase 2 嵌套入口均实际重跑全量，三份 `unit.json` 独立保留。

原 Phase 3 入口未删减：HTTP v2 身份边界、原独立修复、Provider A–K/真实混合边界、
两轮三车型 Action 正常/故障、两轮 Chrome Action Lab 和真实 ROS 2 Jazzy/API 集成全部通过。
原 Phase 1/2 两轮 `run-1-37d2e29d`、`run-2-6c9800f5` 的三车型 A–F 全部通过，包含原 Rover 物理用例、
原生 RTL/HOLD、Copter 物理/故障、Plane Cancel Window 与完整原生控制。

原 Vehicle、Execution、Authority、Safety、认证水位、独立外部生命周期、Provider Identity 与 ROS Service 不确定性代码没有改动；
ActionRuntime/ActionResources 的新增任务成员和连续输入能力未绕过它们。原停止、物理、TTL/Lease、200 ms cycle 等阈值未改。

新 wheel 从安装目录实际启动 Mission CLI，默认车辆为零、未导入 rclpy，三个页面均可访问；
226 个 Python 文件、12 个 Web 文件和 47 个运行资源与受测源码逐字节一致，另外复核全部 setuptools package-data。
wheel SHA-256：`8fc1aa3306079481ed22b0ee63e9e1f8abe4863771c0413c8fe60cc3b23f974d`。
真实 ROS 集成结果位于原回归目录，不把默认 CLI 页面检查冒充 wheel 下的实飞或 DDS 测试。

## 8. 保留的失败与最小修复

首个正式候选 `23f9dd8` 的运行目录 `acceptance-23f9dd8-1/` 仍为 **FAIL**，没有修改历史结论。
当时单元、第一轮三车型 Chrome、Rover/Copter 恢复和 Plane 边界均通过，混合退出超时测试失败：
UNKNOWN 发布后，测试在约 54 ms 后才完成的 Driver finish Future 之前解引用了 None。
日志显示共同资源没有提前释放；仅新测试加入 2 秒有界观察，必须取得真实安全证明，且同时确认外部 Job 仍活动。
这不是延长 Action/Execution 的退出期限，也没有把缺失证据当作安全。
修复后 `dev-mixed-3/`、全量 565 项及新的完整两轮验收通过。

开发阶段还保留空缓冲观测错误、Registry 夹具装配错误、只读重连旧代理、Plane cycle 保护触发、
重复持久化及 wheel 漏装声明 extra 的失败日志。修正夹具、抑制无变化提交、限制观测内存并保留完整文件日志、
减少只读界面重复拷贝与查询；没有放宽 cycle 或物理阈值。混合新测试曾误用通用1秒 TTL，后直接引用原 SetMode 5秒合同。
新增测试文件名曾与原 `mission_faults.py` 冲突，已将旧文件恢复为基线字节，新文件独立为 `phase4_faults.py`；没有删除旧测试。

## 9. 清理、历史与完整性

- 正式运行拥有 52 个 SITL/Gazebo 夹具；连同开发、失败候选，审计共 85 个明确登记的夹具。
- 85 个夹具的私密配置、SITL state、EEPROM及可能含凭据的 BIN 均按原 OwnedCredentials 合同销毁；
  manifest 的 credential_destruction 准确保留旧大小/摘要和 `destroyed_unavailable`。这些二进制现已不可用，不伪造“当前哈希仍一致”。
- 8 个登记仿真端口可绑定，56 条正式阶段进程记录无相关活进程；wheel HTTP 端口另行重新绑定验证。
  应用、代理、Chrome、ROS/API 测试按原 finally 路径退出；没有清理独立用户进程或文件。
- 89 个签名 epoch 摘要各不相同，未在日志/报告/Git 输出认证密钥；日志检查未发现含秘密的 SETUP_SIGNING 记录。
- 3832 项历史证据/文档重新核对无变化，原独立 FAIL、过去正式仿真证据和哈希记录保留。
- 独立 ArduPilot 项目仍干净；独立 Gazebo 插件项目仍只有原有四项未跟踪 CUADC 资源，没有新增修改。
- 非敏感 UNKNOWN Journal/Ledger 保留作证据，未通过删除状态或普通 release 清除危险占用。
- 收尾核验：`finish-checks.json`；清理/历史核验：`audit/summary.json`；文件摘要以索引为准。

## 10. 限制与交付边界

依赖受信本机 OS、固定共享 Registry、诚实 Provider、可靠本地 rename/fsync、明确自有的 AP/Gazebo 和既有 profile。
不提供跨主机锁、恶意 Python 沙箱或实机资格。MAVLink packet sequence 不是请求 UUID，签名时间顺序也不使 ACK 获得请求 UUID；
原认证新鲜度及协议歧义限制继续适用，不声明绝对抗任意重放。

Mission history 为最多256条节点事件的回放窗口，完整 Action 关联单独保留；最多64次任务、128个发布版本，Journal最大4 MiB，
预算耗尽保守拒绝，不逐出 UNKNOWN。Python/OS不是硬实时平台，超时仍由原安全链拒绝或保持不确定。
尚无 Phase 5 感知融合、Mission AI、新硬件控制或分布式协调能力。

受测实现时工作区干净，最终仅增加报告/索引文档提交；交付工作区干净，文档提交后以 `git status --porcelain` 再次核验。
当前具备交给独立审查员重新验收的开发侧条件。到此停止，不进入 Phase 5，不宣布最终 PASS。
