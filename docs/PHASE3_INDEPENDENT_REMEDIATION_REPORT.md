# Phase 3 独立 FAIL 定向修复报告

本报告仅覆盖独立审查发现的 1 项 P1 和 3 项 P2，以及完整回归发现的直接装配问题。最终开发侧状态、受测 SHA 和正式结果见后文；不宣布最终 Phase 3 PASS，不进入 Phase 4。

## 1. 基线与证据保护

本轮在原 `feat/phase3-action-system` 分支工作。开始时 HEAD 为 `03d6521ccd65d72b845ff7941d93935c3e650d15`，其受测代码为 `047bebafaf7bdb6f1d44407606200810da4d80e0`；首个 Git 状态检查为空，没有用户未提交源码修改。

独立结论为 **FAIL，047beba 不可冻结**。原报告 `/tmp/vaf-phase3-independent-pm9xx77k/INDEPENDENT_PHASE3_REVIEW.md` 存在，已阅读报告、四项源码和实际复现。58 项根级报告/复现脚本/JSON 已原样归档到 `artifacts/phase3-remediation/independent-review/`，另保留本轮重新执行的修复前证据；原 `/tmp` 材料未修改。原 Phase 3 开发报告和证据索引保持原字节，不把旧 READY 或独立 FAIL 改成通过。

基线全量单元测试 466 项通过（47.164s，零失败/错误/跳过）。`artifacts/phase3-remediation/baseline.json` 的 clean=false 是在创建当时尚未被忽略的新证据目录后采集的状态，唯一新增未跟踪项是该证据目录；不代表初始存在用户源码修改。后续新增精确 `.gitignore` 规则。历史哈希和本轮完整证据索引另行复核。

## 2. P1：签名接收水位的崩溃一致性

原实现对 `action-receive-floor` 原地截断并单次写入数字，短写后的数字前缀仍能通过“数字”检查，重启又与 provisioning floor 取最大值。本轮重做独立复现：101 帧先被接受，持久化229；更新358注入2字节短写留下35；当次抛异常，但重启加载100，同一101帧再次被接受。原始结果见 `before-watermark/persistence_probe.json`，只 stub 无关的 OS 活进程身份；真实构造、文件权限/锁、MAC和重载执行，没有车辆连接或密钥输出。

修改位于 `app/bootstrap/action_ownership.py` 和共用小型文件工具 `engine/action/durable.py`。新 epoch 由自有 fixture provisioner 在首个 Action owner 之前建立版本化、规范编码、带校验和且绑定 epoch 指纹的记录；接收方绝不自动建立缺失记录，也不升级旧数字格式。更新顺序为私密独占临时文件、检查完整写入、文件 fsync、原子替换、目录 fsync。权限、硬链接/符号链接、大小、版本、编码、checksum、字段类型、epoch、48位界限均检查。

MAC和签名顺序先在候选 verifier 上校验；只有需要的保守 reservation 已完成持久化，才更新公开接收水位/accepted计数并向 Session 返回可信证据。任何持久化异常使该 receiver 进入不可继续接受状态。对于每个已返回的认证时间戳 T，durable_floor≥T；同 epoch 已提交 floor 和返回时间戳不回退。正常重启恢复有效记录，拒绝其水位以内的旧帧；缺失、损坏、截断或错误 epoch 必须拒绝并建立新的可信认证 epoch，不能降回 provisioning floor。

仍使用原有最多128个**签名时间戳增量**的持久化预留，实时逐包MAC/顺序验证；未扩大缓存、改变ACK/HEARTBEAT确认合同，也未改MAVLink序号或车辆状态机。正常新帧高于保守水位后仍可接受。

新增测试覆盖短写有效数字前缀、write/fsync/replace异常、原子替换前后真实SIGKILL、恢复、相同旧帧、时间戳回退、损坏/丢失/错误格式/epoch，以及合法新帧。它们使用真实文件和真实签名验证，不把内存替身称为SITL验收。

## 3. P2：退出异常/超时不能被车辆 guard 覆盖

原通用 Runtime 的 exit 异常仅设置 FAILED/complete；外部 Driver 无车辆需要清理，返回 release_safe=true，错误释放资源。另一条路径在退出超时首 tick UNKNOWN/retain，下一 tick 直接采纳 guard_stop 的 true 结果而清空占用。本轮新边界测试在修复前分别得到 FAILED错误释放、UNKNOWN后多tick释放，见 `before-boundaries.log` 和独立 `exit_probe.json`/`hung_exit_probe.json`。

`manager.py` 统一组合外部退出证据和 Driver 安全证据，包括终态后的 guard future 和后续 guard_status。外部生命周期 exit异常、未确认退出期限、无句柄准入异常形成独立不确定性；“无车辆清理”不能消除它。普通 FAILED、可信终态、明确无副作用拒绝和 Query 不一律改成UNKNOWN。已声明的Typed车辆Effects仍由原Driver独立确认退出，原车辆取消/超时安全回归保留。

测试核对超时/异常后的多个tick、实际provider创建次数、资源与后续拒绝/等待超时，不再只观察首个UNKNOWN标签。无副作用Query和明确ActionAdmissionRejected能释放，正常任务仍能运行。可信外部终态可经受控对账解决，原逻辑UNKNOWN结果不被篡改成成功。

## 4. P2：ROS提交后通信失败必须保持不确定

原 worker 仅在取得已接受的Action handle后设置accepted，Service分支始终false。call_async/send_goal_async已经发出后异常仍被写成FAILED，ExternalInstance因此释放资源。

新规则在尝试提交之前设置submission_started。提交前不可用/明确拒绝仍为FAILED，提交后的Future/通信异常默认为UNKNOWN；正常实际终态继续映射为成功、取消或终态失败。Trigger没有取消/状态查询协议，关闭本地worker不能证明服务停止；没有自动重发来掩盖未知结果。API恢复仅GET既有Job ID；运行时的自动读对账在有界后台线程进行，不在正常tick中阻塞网络。

本轮修复前用真实ROS 2 Jazzy、DDS、Trigger Server、ProcessJob、ExternalFactory、Runtime重现：服务端started标记已产生、仍执行4秒，客户端spin_once处注入一次异常，旧结果FAILED、release_safe=true、claims=[]，同资源正常请求实际执行。原始结果见 `before-ros/ros_real_probe.json`。

修复后用项目内 `tests/simulation/remediation_external.py` 独立复现同一真实链路：UNKNOWN且占用保留，同资源请求REJECTED且没有normal-started标记；Query可完成。服务端可信同次invocation终态出现后，受控对账释放占用，再运行正常成功、实际终态错误、提交前不可用。这个服务端标记是**受控测试oracle**，没有把它伪称为通用Trigger查询协议；生产中没有这种证据就必须保持占用。原真实Wait Action的Goal/Feedback/Result/Cancel/Timeout/错误/断连正常集成继续执行。

## 5. P2：跨应用重启的外部占用

原 resources/records/API Job ID 只有内存状态。本轮修复前运行真实HTTP JobServer与两个独立ActionLab应用进程：杀死首个应用后旧20秒作业仍RUNNING；新应用再次RUNNING，服务端存在两个同时运行作业。证据见 `before-api/restart_probe.json`，没有车辆写入。

`resources.py` 增加仅用于外部副作用的持久化reservation，**不授予车辆SEND/Lease，不替代原Authority**。在provider factory调用之前落盘，并在实际启动前提交ACTIVE标记。记录包含Action/name/version、owner/runtime UUID、PID/start_ticks、稳定作用域、target、资源模式/冲突组、未知状态及可获得的endpoint/Job ID；不存API token或密钥。取得ID之前死亡也有先前reservation，默认阻止重复提交。

跨进程文件锁和原子带校验记录串行化竞争。目标别名、新Action/Runtime身份、PID死亡都不等于旧工作已停止。普通启动绝不初始化缺失namespace；首次建立需要可信部署对新鲜/空闲provider的明确校验，scope与目录须跨重启保持不变。已有目录、锁、记录或相邻身份anchor损坏/缺失则拒绝复用。不存在删除文件、force boolean或普通release清除旧未知占用的支持路径。目录和4MiB/4096记录有界，不逐出危险占用。

`ActionRuntime.reconcile_external` 是可信部署代码调用的有限恢复路径，不是Web强制释放入口。已知Job ID可通过 `reconcile_api_resource` 读取真实provider状态，RUNNING/UNKNOWN/错误不释放；没有Job ID必须验证provider整体空闲或精确调用终态。新协调者不能解除仍存活旧协调者的占用；PID复用按start_ticks区分。相同协调者也只能对账其逻辑终态且Driver清理已确认的记录。对账事件与安全视图同步，逻辑UNKNOWN历史不改写。

真实多进程测试分别覆盖已取得ID、服务已启动但ID尚未返回。旧应用仍存活时与SIGKILL重启后，target别名的冲突请求均拒绝，服务端始终只有1个未解决作业；可信终态/受控完整inventory后才允许新的正常作业成功。另有同时启动竞争、状态短写、锁/文件/目录丢失和无副作用读取测试。所有测试存储独立，绝不借新目录复用仍运行的同一provider。

## 6. 正式回归发现的直接装配问题

`745f20860556ae62067c5f21a972a3c456bdb942` 已通过当时488项单元、真实外部边界和wheel，但首个真实Rover在owner准入失败：有效接收记录先建立，SITL的签名参数回读又推进了provisioning fence，接收记录略早。原规则过度拒绝合法fixture。该次正式运行如实为FAIL，零Action/零实际Writer，清理通过，保存在 `acceptance-745f208-1/`。

后续最小修复只允许向更高的可信provisioning fence推进**现存、完整校验、同epoch**的有效记录，并在接收方使用之前持久化；不存在/损坏仍拒绝，绝不退回较低值。新增对应正向回归。另启动独立真实只读fixture验证修复前/后准入，不授予控制权、零Writer；记录 `diagnostic-owned-floor-1/`。显式SIGINT使诊断入口记录InterruptedError退出，manifest确认密钥/状态、进程和端口全部清理；未把中断说成完整验收通过。

开发诊断还保留：过度保守分类曾阻止已确认车辆Driver清理的资源释放，随后按明确Typed车辆Effect与未知外部生命周期区分，原车辆测试原断言恢复通过；新ROS测试的Python搜索路径和重复shutdown仅为测试装配问题，已修正，失败日志保留。一次错误的unittest包入口运行0项，未作为测试通过证据；正式计数全部来自discover/harness。

## 7. 使用限制与复现

完整恢复合同、API及失败处理见 [INDEPENDENT_REMEDIATION_CONTRACTS.md](phase3/INDEPENDENT_REMEDIATION_CONTRACTS.md)。本修复依赖可信OS所有者和实现原子rename/文件及目录fsync语义的本地存储。checksum用于识别意外损坏，不是防同权限恶意篡改或完整快照回滚的密码学认证。若无法证明认证窗口/外部占用的恢复，拒绝复用，建立新的可信认证/真正隔离provider epoch；不能仅改目录/实例身份假装恢复。

MAVLink签名顺序不是命令UUID或车辆采样时钟，不扩大原Phase1协议承诺。ROS Trigger没有通用的结果查询/取消；外部provider必须诚实提供终态与安全语义，无法证明时保持UNKNOWN。可信部署负责稳定scope与存储的绑定；本轮没有全局远端安全系统、Mission持久化或自动任务恢复。没有改实机入口或启用实车。

```bash
.venv-migration/bin/python -m unittest discover -s tests -v
.venv-migration/bin/python -m tests.simulation.remediation_external \
  --run-dir artifacts/phase3-remediation/external-UNIQUE
./scripts/test_phase3_actions.sh --allow-send \
  --sitl-bin-dir artifacts/phase2-control/ardupilot-source/build/sitl/bin \
  --run-dir artifacts/phase3-remediation/acceptance-UNIQUE
```

正式入口先跑全量单元与新的真实API/ROS边界，再跑原两轮三车型Action/Chrome/ROS A–F及原两轮Phase1/2回归G。只新增检查，不删除/跳过旧测试或放宽物理/安全阈值。

新增23项单元边界用例：`tests/action_system/test_durable_watermark.py`（6项）、`test_independent_boundaries.py`（7项）、`test_persistent_resources.py`（10项）。另新增真实集成入口`tests/simulation/remediation_external.py`；原运行时测试只收紧危险退出的UNKNOWN/占用断言，并适配版本化持久记录与显式可信初始化，没有放宽既有控制断言。

## 8. 正式结果：READY FOR RE-AUDIT

受测提交：`483253498ae317bc2ff6bdee53bd8ba62a76ff94`。前后源码/测试/脚本/资源SHA-256均为 `c20f8db41b229c0925546432b129f7ad9b2fa5c056a581df0a4ec34f2dbafeb9`。

UTC运行时间：2026-10-25T07:27:49.106352+00:00 至 2026-10-25T08:39:54.430234+00:00。[原始汇总](../artifacts/phase3-remediation/acceptance-readback-1/summary.json)。全量 489 项单元，零失败、零错误、零跳过；原回归自身再次运行全量单元也通过。

| 轮次 | Rover正常/故障 | Copter正常/故障 | Plane正常/故障 | 外部接口 | A–G |
|---|---|---|---|---|---|
| 1 | 通过/通过 | 通过/通过 | 通过/通过 | 11项通过 | 全部通过 |
| 2 | 通过/通过 | 通过/通过 | 通过/通过 | 11项通过 | 全部通过 |

两轮新Action真实三车型场景共12个，另有两轮原Phase1/2三车型完整回归18个，均由独立Gazebo真值确认物理运动，不把ACK/模式确认当成到达/着陆。真实Chrome每轮经过Web→Runtime→Execution→SITL→Gazebo→Result，并核验刷新保留同实例。

原回归：[原始汇总](../artifacts/phase3-remediation/acceptance-readback-1/phase2-regression/summary.json)。

| 原回归轮次 | Rover A–F | Copter A–F | Plane A–F |
|---|---|---|---|
| `run-1-6e9a1750` | 全通过 | 全通过 | 全通过 |
| `run-2-1601f6bc` | 全通过 | 全通过 | 全通过 |

### 8.1 四项边界修复前/后矩阵

| 边界 | 修复前本轮实际复现 | 修复后确定性/真实验证 |
|---|---|---|
| 水位短写/恢复 | 旧101帧重启再次通过，floor回退100 | 真实文件/MAC及短写/异常/SIGKILL恢复：旧帧拒绝，合法高时间戳可通过；缺失/损坏拒绝恢复 |
| 退出异常 | FAILED且claims清空，旧provider仍active | UNKNOWN，多个tick仍保留；新实例拒绝，provider创建次数不增加 |
| 退出超时后的下一tick | 首tickUNKNOWN，随后被Driver true结果错误释放 | 独立外部不确定性保留；车辆清理不覆盖；原Typed车辆清理正向测试通过 |
| ROS提交后Future错误 | Action/Service都错误FAILED | 两接口均UNKNOWN；明确拒绝/提交前不可用/正常Service保留原正确终态 |
| 真实ROS已执行Service后客户端异常 | 服务仍执行，FAILED释放，新同资源调用成功 | UNKNOWN保留、同资源REJECTED且未启动；Query通过；可信同次终态后安全对账和新成功 |
| HTTP作业/应用SIGKILL重启 | 两个独立应用造成两个并发RUNNING作业 | 已知ID和未知ID两场景：活跃竞争/重启均拒绝，服务端只有1个未解决作业；可信对账后新作业成功 |
| 同时竞争/新身份/直接release | 原实现仅内存，重启默认空闲 | 真实双进程竞争仅1个reservation；旧活跃协调者不可被新协调者解除；普通release不能清除未知占用 |
| 持久状态缺失/损坏/短写 | 原本没有跨进程占用记录 | 拒绝副作用，不自动初始化；Query仍可读取；新鲜/空闲provider经显式初始化后正常使用 |

冻结提交的真实边界场景：[原始汇总](../artifacts/phase3-remediation/acceptance-readback-1/independent-remediation-boundaries/summary.json)。具体值：

| 场景 | 实际关键结果 |
|---|---|
| api_restart_known_id | 4个独立应用进程；活跃竞争=REJECTED，重启=REJECTED，对账前作业数=1；新作业=SUCCEEDED；MAVLink Writer=0 |
| api_restart_before_id | 4个独立应用进程；活跃竞争=REJECTED，重启=REJECTED，对账前作业数=1；新作业=SUCCEEDED；MAVLink Writer=0 |
| actual_ros_service_result_lost | 真实DDS服务已开始=True；异常=UNKNOWN，冲突=REJECTED，Query=SUCCEEDED；恢复后成功=SUCCEEDED、终态错误=FAILED、未提交不可用=FAILED |

### 8.2 两轮正常控制与故障正反对照

| 轮次/车型 | 真值及安全边界 | 证据 |
|---|---|---|
| 1/rover | 正/反位移1.0054/1.0090m，正/反转0.8192/0.8013rad；Goto误差0.1896m；Chrome刷新同实例=True，取消后速度0.001235m/s；未知交接Writer=0 | [原始汇总](../artifacts/phase3-remediation/acceptance-readback-1/round-1-fb4f0163/rover-actions/summary.json) |
| 1/copter | ENU位移1.1450m，FLU投影1.1469m；实际Takeoff/Goto/Land/返航通过；未知交接Writer=0 | [原始汇总](../artifacts/phase3-remediation/acceptance-readback-1/round-1-fb4f0163/copter-actions/summary.json) |
| 1/plane | 实际滑跑20样本、最大速度18.7742m/s，爬升51.6626m；AutoLand着地稳定/认证解除武装；故障ACK丢弃1、转发0、应用接收0，TAKEOFF实际Writer=1，未知交接Writer=0 | [原始汇总](../artifacts/phase3-remediation/acceptance-readback-1/round-1-fb4f0163/plane-actions/summary.json) |
| 2/rover | 正/反位移1.0300/1.0088m，正/反转0.7920/0.8019rad；Goto误差0.2351m；Chrome刷新同实例=True，取消后速度0.001482m/s；未知交接Writer=0 | [原始汇总](../artifacts/phase3-remediation/acceptance-readback-1/round-2-2e31f87a/rover-actions/summary.json) |
| 2/copter | ENU位移1.1350m，FLU投影1.1362m；实际Takeoff/Goto/Land/返航通过；未知交接Writer=0 | [原始汇总](../artifacts/phase3-remediation/acceptance-readback-1/round-2-2e31f87a/copter-actions/summary.json) |
| 2/plane | 实际滑跑19样本、最大速度18.7745m/s，爬升51.6582m；AutoLand着地稳定/认证解除武装；故障ACK丢弃1、转发0、应用接收0，TAKEOFF实际Writer=1，未知交接Writer=0 | [原始汇总](../artifacts/phase3-remediation/acceptance-readback-1/round-2-2e31f87a/plane-actions/summary.json) |

正常签名ACK/HEARTBEAT、连续Arm/Disarm和各Action实际完成都通过，未靠拒绝全部确认取得结果。原回归继续覆盖序号回绕旧ACK+HB、Writer锁/Guard/Lease过期零写、会话/重连、取消与安全停止。原有门槛不变。两轮真实外部集成分别仍验证成功、反馈、取消、超时、不可用、错误和断连UNKNOWN。

## 9. Wheel、清理与完整性

独立wheel安装与真实ROS worker通过：[原始汇总](../artifacts/phase3-remediation/wheel-final-check/summary.json)。214个Python模块、44个配置/资源文件、6个Web静态文件逐字节匹配受测代码，入口、默认未连接/双SEND关闭、ROS wrapper完整；主应用无rclpy导入。wheel SHA-256：`929377c7f351d7802e1365a508898ebb131bce320ddefd3d6ded27add856fcd7`。

wheel烟测使用的原ROS测试服务器在SIGTERM后重复调用shutdown，stderr记录RCLError。实际已安装Action成功并收到真实反馈，服务器已退出；该旧fixture的退出诊断不作为功能通过证据，也未修改或隐藏。原始`wheel-final-check/ros-server.log`纳入索引。

最终审计 [原始汇总](../artifacts/phase3-remediation/delivery-audit.json)：30个正式SITL/Gazebo fixture以及本轮失败/诊断fixture清理通过；自有PID/start_ticks均不存活、记录端口可绑定、没有注册私钥/EEPROM/SITL state残留。38份原始帧日志未保留SETUP_SIGNING报文。凭据销毁记录只保留原哈希和unavailable，不伪称可离线重验已销毁密钥的MAC。

外部未知reservation文件作为非敏感证据保留，不在shutdown强行清空。实际测试HTTP/ROS provider和客户端均退出/关闭，不把关闭本地句柄称为通用远端停止证明。

旧Phase3保护文件489项、更早历史文件739项、独立FAIL根级原件58项均哈希不变。车辆、Execution、Authority、Safety、BasicAction、旧SimulationRuntime、模型/参数与阈值无修改；没有删除原测试。

完整本轮证据索引：[independent-remediation-evidence.json](phase3/independent-remediation-evidence.json)。所有新增原始记录位于`artifacts/phase3-remediation/`；原证据不覆盖。

## 10. 提交与交付状态

- `745f20860556ae62067c5f21a972a3c456bdb942`：四项定向修复、边界测试与恢复合同。该候选首次真实Rover准入失败，不能单独作为最终合格候选。
- `483253498ae317bc2ff6bdee53bd8ba62a76ff94`：仅补合法签名参数回读fence推进及正向回归；本报告完整受测提交。

正式验收开始时工作区干净，前后受测摘要一致。提交前仅README、本报告、恢复合同补充和新证据索引四项文档变更，源码及测试无未提交修改。交付文档单独提交；最终提交SHA和提交后工作区核验见[交付状态](../artifacts/phase3-remediation/delivery-state.json)、Git日志及交付消息。该提交后记录不纳入自引用证据索引。

未解决的阶段内强制失败：无。协议/存储/可信provider边界限制见第7节和恢复合同。最终开发侧状态 **READY FOR RE-AUDIT**，等待独立复审；不自行宣布PASS，完成后停止，不进入Phase4。
