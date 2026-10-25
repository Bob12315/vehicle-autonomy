# Phase 4 Mission 与手动控制合同

本页描述实现合同；正式验收状态以 `PHASE4_MISSION_AND_CONTROL_REPORT.md` 的实际结果为准。仅限明确自有的本机 SITL/Gazebo，不开放硬件运动、Phase 5 感知融合或 AI。

## 装配和入口

`vehicle-autonomy-missions` 沿用 Action Lab 的 owned manifest 验证、loopback HTTP、私密 Bearer、CSRF、Host/Origin、请求体/线程上限与不可逐出的幂等 ID。`/` 仍是 Action Lab；`/studio` 是图编辑器，`/control` 是三车型控制中心。普通入口没有车辆，双 SEND 默认关闭。每个写任务/操作还必须显式授权 SEND。

```bash
# 先在新目录明确启动自己的 fixture，二进制采用项目内隔离构建。
VAF_SIMULATION_SITL_BIN_DIR="$PWD/artifacts/phase2-control/ardupilot-source/build/sitl/bin" \
  .venv-migration/bin/python -m tests.simulation.action_lab_fixture \
  --kind rover --run-dir artifacts/phase4-mission/operator-rover-UNIQUE

# 另一个终端。只在首次建立受信本机部署时添加初始化选项；已建立/损坏的 Registry 不可重置。
vehicle-autonomy-missions --simulation rover=artifacts/phase4-mission/operator-rover-UNIQUE/manifest.json \
  --data-dir runtime/mission-control --token-file runtime/mission-control/token \
  --initialize-provider-registry --allow-send
```

可重复 `--simulation TARGET=MANIFEST` 加载三个独立 fixture。ProviderRegistry 使用 Phase 3 固定 OS 账户根；scope、安装位置、环境变量和 data-dir 不能选择第二根。同一个真实 SITL epoch 只能绑定一个 Mission Journal 和 target 标签。另一个目录、别名、同时初始化均在执行副作用之前拒绝。新增绑定不改动既有 Provider/认证存储格式。

`--initialize-provider-registry` 仅用于明确的新部署 bootstrap，绝不是恢复按钮。既有 Registry 缺失、损坏或绑定不一致则拒绝启动控制。测试只在夹具中替换私有存储位置，所有同一病例的应用共享该根；生产入口不读取测试位置环境变量。

## MissionSpec 1

JSON 包含 `schema_version=1`、`id/name/version/target/root/nodes`，可选 `timeout_s`、`required_capabilities`、`blackboard`、`resources`。Action 节点引用 Registry 的精确版本，未指定时在验证阶段锁定；能力、车型、参数和派生资源均需匹配。发布的 `id@version` 内容不可改写，新草稿使用新版本。节点 ID、每次节点 execution ID、Action ID、Mission run ID 独立。

图是有序、有根的树；`children` 是连接，禁止环、共享可变节点、孤儿及未知字段。上限 128 节点、深度 16、每个复合节点 32 子节点、Repeat 20 次、每次任务最多 256 Action，总期限不超过 1800 秒。运行锁定不可变定义；保存和加载不会替换运行中的图。示例在 `simulation/missions/{rover,copter,plane}.json`，wheel 同时携带。

| 节点 | 语义 |
|---|---|
| Action | 仅向同一个 ActionRuntime 提交精确版本，观察逻辑结果与独立安全结果 |
| Sequence | 按连接顺序；前项完成后启动后一项；UNKNOWN 不继续 |
| Parallel | completion=`all/any/main`，failure=`fail_fast/all_failed`；终止前清理余项，不能忽略未知副作用 |
| Condition | 0 个分支作断言，2 个分支 TRUE/FALSE，3 个分支额外 UNKNOWN；UNKNOWN 分支只准查询/等待 |
| Fallback / Recovery | 仅已安全退出的确定失败进入备选；UNKNOWN 不进入新运动 |
| Event | 等待订阅之后的新鲜事件后启动子节点 |
| Reactive | main 与事件监听共存；事件触发先取消 main，可信退出后再启动 response；不确定则停止 |
| Wait / Timeout / Repeat | 有界等待、独立节点期限、有限重复；重复创建新的 execution/Action 身份 |

Parallel 静态拒绝同一资源冲突；运行时仍使用现有 ActionResources。Mission 在子 Action 之间也保留任务资源，不能由原 Action Lab 或直接 ActionRuntime 提交插入新控制。子 Action 使用不可序列化的进程内成员许可，但仍分别互斥；该许可不能替代 SEND、Lease、Authority、Safety 或 Writer 的最终检查。

## 只读条件、参数与事件

条件只支持 `eq/ne/lt/le/gt/ge/all/any/not`，无 Python eval。来源为 world 或 blackboard，带原始时间、时域、质量和 frame。TRUE/FALSE/UNKNOWN 分离；缺失、过期、未来时间、错时域、错 frame、不可比类型均 UNKNOWN，布尔不与数字混用。默认观测最大年龄 3 秒，表达式可显式要求更严格或更长的业务年龄；AP 源自身仍受既有新鲜度与签名合同限制。

Action 输出保留最初 result_at，不以退出完成时间刷新；嵌套 World/Stamped 数据保留其原始采样/发布时间和质量，不能借助新的外层结果提升旧状态。Blackboard 初始常量在任务开始赋值，条件可显式设置适合其有效期的 `max_age_s`。

参数可使用以下受控绑定，运行前重新核验时间/质量/frame，并通过同一个 Registry 参数 Schema；缺失先有界等待，仍不确定则 UNKNOWN。offset 使用该字段已声明的单位，不做隐式坐标变换。

```json
{"$query":{"source":"world","path":"vehicle.global_position.value.latitude_deg","frame":"earth","max_age_s":3,"offset":0.001347472926179282}}
```

事件包含身份、单调序号、来源、质量和 TTL。每个节点记录消费水位；相同身份不能因 Repeat 再触发。发布和事件历史有上限，不逐出旧 ID 让重放重新有效。Phase 4 的 LocalEvents 是明确注入的确定性事件源，不是 Camera/YOLO/SLAM 的实现。只读 WorldSnapshotProvider/EventSource/BlackboardValue 和现有 ResourceReference/WorldSnapshot.map 为以后接入保留合同，不伪造融合/地图能力。

## 连续输入与控制权

Rover 使用原 Drive，Copter 使用原 SetVelocity；输入只更新同一个 Continuous Action 的不可变参数，不新建运动 Writer。服务器要求递增序号和上一响应的一次性期限票据，最多 20 Hz，参数受原 Schema 限幅；本 UI 发送 10 Hz，票据按十进制字符串传输避免长 uptime 的 JS 整数精度丢失。

输入期限 0.4 秒，普通运动 Effect 的 deadline 同时截断到该期限。Action 自身最大生命周期不被更新延长。过期、取消、链路/会话变化后不能复活，重新操控必须重新授权。松键、失焦、页面隐藏、断网停止更新；服务器和原 Execution/唯一 Writer 独立处理 deadman、TTL、Lease、Session/Generation。停止仍用原来的物理退出期限与阈值，无法确认时保持 UNKNOWN/UNCONFIRMED 和占用。输入更新只保证开始受控写入，不声称车辆已经执行。

手动与 Mission 在同一 Runtime/资源表/Driver/Authority 上运行。takeover 只请求安全退出，不授予权限；取消中拒绝新普通运动，未知结果保持阻挡。Plane 只使用原生 Takeoff/SetGuidedTarget/Loiter/RTL/AutoLand；无 RC override、舵面直控、零速停车或空中 Disarm。已成功且保留的 native flight 可显式 continuation；运行中的 Mission continuation 不能被外部旧 ID 抢走。资源已转交不等于车辆已停止，配置成功不等于抵达/降落。

## 重启、持久化和受控恢复

Journal 使用原 DurableRecord 的校验、短写检测、原子提交、文件及目录 fsync；独立目录 anchor 和 lifetime flock 检查缺失、替换与重复应用。节点/Action 意图在副作用回调之前持久提交。手动输入同样记录 SUBMITTING 意图和精确版本/资源/Provider 绑定。存储异常关闭新入口，但不会抑制 Action 的安全退出 tick。未改变的状态不重复持久化。

重启把未解决任务/手动记录恢复为 UNKNOWN，恢复资源阻挡，不重建旧 Action、控制输入、Lease 或 SEND。相同真实 SITL 不能通过改目录/target 取得第二本 Journal。`/api/control/reestablish` 是受控证据重建，不是 force release：必须没有当前未结束控制，验证签名接收、只读授权状态、新鲜 VALID odom、未解锁静止地面，且为同一 owned identity；更换 fixture 时还要核验旧 SITL 和 Gazebo 的完整退出/凭据清理清单及 PID/start_ticks。

车辆地面状态不能证明独立 HTTP/ROS/Native Job 结束。外部责任必须关联 Journal 固定的 Provider 绑定，经原 Phase 3 可信对账使有效持久 Ledger 无未解决占用；绑定缺失/改变、Ledger 损坏或仍有作业一律拒绝。没有管理型 Provider 证据的 opaque 责任不能靠 UI 布尔值解除。恢复不改写旧 UNKNOWN 为成功，不发送命令；下一操作仍需新的双 SEND 授权。

条件/事件未知不是普通 FAILED；取消不是停车；Action 成功、物理目标、外部终态、资源可释放分别保留。操作台展示的是 AP 发布的 odom ENU 或 earth 经纬度/AMSL，不使用 Gazebo 真值控制车辆，也不把两者视为默认同一坐标。

## 运行预算与可观测性

单 Runtime 最多 512 个 Action、每个 Action 2048 个 Effect，反馈 100 条、Action 历史 128 条；Mission 最多 64 次运行、128 个已发布版本，Journal 最大 4 MiB。预算首先触及即保守拒绝/请求退出，不逐出未知占用。每次 Mission 最多 256 个 Action，事件源最多 1024 个身份；事件/历史不能无限增长。

Studio 当前回放为最多 256 条节点事件的窗口；Action 实例与独立身份仍可查询，不把窗口外历史伪装成完整回放。长任务的详细反馈、资源与错误可从状态接口/验收原始日志追溯。当前节点使用实际节点状态，不由前端执行图决定。服务器以 20 Hz 调度；手动输入 10 Hz，完整遥测页 2 Hz。Python/本机 OS 不是硬实时环境，原有 cycle 时限、Writer、Lease/TTL 和认证接收保证仍独立生效，超时保持不确定而非继续控制。

## 验证入口

```bash
python -m unittest discover -s tests -v
./scripts/test_phase4_missions.sh --allow-send \
  --sitl-bin-dir artifacts/phase2-control/ardupilot-source/build/sitl/bin \
  --run-dir artifacts/phase4-mission/acceptance-UNIQUE
```

正式入口要求干净的已提交源码，在新目录串行运行两轮真实 Chrome 三车型 Mission/Manual、Rover/Copter 故障/重启、Plane 跨主体续接/ACK 丢失/回绕重放及混合 HTTP Job，再调用未经删减的 Phase 3 入口完成两轮 Action/ROS/API/Chrome 和原 Phase 1/2 全部回归。Gazebo 真值仅用于独立验收。签名材料、EEPROM、端口和自有进程必须清理，历史 FAIL 和过去验收文件不得覆盖。

这是受信本机、固定 Registry、诚实 Provider、本地可靠原子存储的合同；不提供跨主机锁或恶意 Python 沙箱。没有默认实机运动、Camera/YOLO/LiDAR/SLAM 融合或 AI 能力。
