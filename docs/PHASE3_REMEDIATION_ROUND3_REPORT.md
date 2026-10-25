# Phase 3 第三轮定向修复报告

本轮只修复 R2-P2-A 与 R2-P2-B，不重做 Phase 3，不进入 Phase 4。开发侧最终状态、实际受测提交和正式结果见后文；不宣布 Phase 3 PASS。

## 1. 基线和历史证据

基线 HEAD 为 `d93dd7b5a4e8bfe90445c53c8255c929ab8b0bda`，对应受审实现 `483253498ae317bc2ff6bdee53bd8ba62a76ff94`。原分支 `feat/phase3-action-system`，首次检查工作区干净。基线全量489项单元通过（48.221s），无失败/错误/跳过。

完整阅读 `/tmp/vaf-phase3-rereview-HQaYc8Al/INDEPENDENT_PHASE3_REREVIEW.md`、原始复现/JSON和相关实现。第二轮独立结论 **FAIL**，没有可冻结的 Phase 3 SHA；原 P1 水位恢复、ROS Service 不确定性检查通过。61项根级审查程序/报告/日志/JSON原样归档到 `artifacts/phase3-round3/independent-rereview/`，另复制必要非敏感原始混合/外部证据，未复制venv、密钥或EEPROM。

本轮建立2052项历史文件的独立大小/哈希基线，覆盖前轮新旧证据索引及保护集合。第一轮独立FAIL、第二轮独立FAIL、既有水位/ROS通过结论和历史真实仿真通过材料均不覆盖。第一轮原58项、第二轮原61项及各自归档副本另作原件哈希检查。基线记录 `artifacts/phase3-round3/baseline.json`。

## 2. 修改前的实际复现

将独立程序复制到本轮 `before/`，只改证据根路径，实际重新执行旧实现；原 `/tmp` 报告、程序及结果未修改。

- `before/runtime_probe.json`：无车辆Effect声明时正确保持UNKNOWN/1个provider；只加ArmEffect声明，Exit异常或超时后资源清空、第二实例RUNNING、provider数量变成2。
- `before/hybrid-real/independent-result.json`：真实未修改VehicleActionDriver +新签名Rover SITL/Gazebo +真实HTTP JobServer。声明ArmEffect、实际尚未发Effect，Exit异常后首实例FAILED且release_safe=true、claims=[]，第二实例RUNNING，HTTP中2个作业同时RUNNING；实际Writer=0。
- `before/provider_binding_probe.json`：同一真实空闲Provider、同epoch，两个目录的真实空闲验证均成立且均初始化成功。4个独立应用得到RUNNING/REJECTED/RUNNING/RUNNING，同一服务中实际3个RUNNING；没有删除、损坏或回滚文件，首协调者仍活着。

对应本轮日志为 `before-runtime.log`、`before-hybrid.log`、`before-provider.log`。上述是修复前缺陷证据，不算作修复后通过。

## 3. R2-P2-A：独立维护两类退出责任

根因是三处外部不确定性分支以 `not s.effect_types` 为条件。车辆“无Effect待清理”仅能证明车辆侧安全，不能证明HTTP/ROS/Native作业结束。

`ActionSpec.external_lifecycle` 现在明确区分 typed_only / managed / opaque（默认）。标准车辆catalog显式声明typed_only，不允许独立外部作业；effect_types仍只用于校验/分派车辆Typed Effect，不再用于推断外部生命周期不存在。Query和明确无副作用拒绝保留正常退出语义。

新增小型 `ExternalLifecycle` 与 `ActionContext.external_jobs` 受控端口。自定义SDK/Job工厂在 `start(create)` 里先登记责任再调用工厂；内置HTTP、Native和ROS进程客户端也在POST、线程或进程启动前自行登记。端口核对当前回调、Action期限、ACTIVE持久owner/runtime、provider身份与声明合同。退出立即封闭端口；保存的端口、后续线程或逻辑终态不能再用它启动作业。同一绑定独占资源不能同时登记两个未解决作业。

manager统一组合车辆Driver证明、退出回调证明和外部作业证明。任一未解决则UNKNOWN并保留共同危险占用；车辆guard、后续tick和逻辑终态不能覆盖外部责任。managed合同下，实际Job可信终态和车辆清理均成立后可正常释放；opaque异常仍需明确完整外部对账。恢复安全不把旧UNKNOWN历史改成成功。资源视图同时展示混合Action的本地车辆资源及持久provider资源。

这不是Python沙箱。Action扩展是受信代码，任意绕过受控接口的原始网络/SDK I/O、未登记副作用线程、虚假终态均违反扩展合同；不声称隔离同进程恶意Python。内置客户端自身会拒绝未登记使用，不只是文档要求。

## 4. R2-P2-B：固定本机身份根与唯一Ledger绑定

旧anchor只识别目录，acquire跳过其他scope；没有真实provider/resource到唯一协调身份的绑定。两次真实且为真的空闲检查不能避免其后创建两份独占ledger。

新增 `ProviderRegistry`，生产根由OS账户密码数据库的home固定为 `~/.local/state/vehicle-autonomy/provider-registry`。安装目录、state_dir、scope、目标别名、实例UUID、XDG和普通环境变量不能选第二个生产注册根。仅受信部署显式首次initialize；普通启动不自动初始化或修复。注册表、锁、目录身份anchor、checksum及ledger绑定在每次事务校验；跨进程固定锁顺序。

Provider/resource绑定先持久提交，再创建唯一ledger。中间崩溃只产生保守阻塞，不给第二目录补建独占空间。绑定固定资源定义和scope，资源换名不产生新冲突域。4096条/4MiB有界，不逐出未知占用。PID死亡、应用重启和flock释放均不表示远端结束。

HTTP通过实际公开只读 `/identity` 返回provider_id、provider_epoch、resource_id=jobs，初始化结合可信完整inventory；客户端在POST前再核对真实身份。同服务URL别名不能改变实际ID；没有该身份接口的Provider不能启动HTTP作业。恢复在GET既有Job ID前也核对实际Provider；无ID仍需要完整可信inventory，不自动POST重试。

ROS使用受信部署绑定的本地域/服务命名空间及epoch，重叠namespace不能登记第二冲突域；ProcessJob核对实际安装ROS worker、参数和domain，不允许用任意命令声称另一个端点。Native合作式ai.inference使用固定OS-user/boot身份，不接受任意Native标签分裂为第二Provider；不将其扩大为任意远程SDK身份认证。

两个真正不同HTTP Provider可独立并发。这个合同仅覆盖同一受信OS账户部署的共享本机协调；不是跨任意主机/用户的分布式锁，不抵抗同权限恶意存储篡改、完整快照回滚、失效fsync或Provider谎报身份。协议不支持身份或不能证明恢复时保守拒绝，不能改目录/scope冒充新epoch。

## 5. 新增边界测试与正常对照

新增 `tests/action_system/test_round3_boundaries.py` 12项：车辆声明未发送/实际发送、外部异常/超时、车辆guard安全但外部仍运行、多tick、新实例竞争、可信终态恢复、opaque单独对账、Query/typed_only不得启动外部作业、终态后端口封闭、scope/环境不能换注册根、重复初始化、损坏/缺失/短写及正常重用。

新增 `tests/simulation/round3_boundaries.py`：真实HTTP服务与独立应用进程运行A–K矩阵；两个真实VehicleActionDriver +新Rover SITL/Gazebo +HTTP场景分别验证未发送车辆Effect的退出异常，以及实际ModeEffect(HOLD)与外部Job并存时退出超时。没有mock车辆Driver、网络、DDS、SITL或Gazebo。所有实际写帧和调用次数有原始记录。

原测试未删除、未跳过；仅适配新的身份bootstrap、独立Provider ledger及明确typed_only合同，原断言保留。HTTP测试服务用独立server-side worker作为真值，不再依赖应用端NativeJob的受控客户端入口；原时限和行为不放宽。正式入口只增加新的先行边界阶段，不减少任何旧场景。

所有测试注册根仅在夹具中替换私有存储位置，同一夹具全部进程共享该位置；生产代码没有可配置第二根的公开参数/环境入口。真实ROS异常注入仅替换测试worker可执行定位，让真实ros_worker在服务started后抛一次spin_once异常；身份/ledger/DDS未替身。正常两轮DDS均使用实际安装worker及未修改的命令验证。

原独立水位探针另在本轮 `watermark-recheck/` 复制改路径重跑，16组真实文件/MAC/重载/3个SIGKILL点通过，旧ACK/HB拒绝、合法新帧通过，临时随机签名密钥已销毁。只有与存储测试无关的活SITL进程身份证明按原探针stub；没有冒称该存储探针为车辆运动验收。

首个候选冻结前500项单元通过（51.841s），新的真实矩阵/混合场景和原真实ROS Service/API重启入口均通过，但第一次正式验收随后发现下述终态分类问题，结论如实保留FAIL。补修后501项单元通过（49.424s），未冻结的单独真实Copter诊断通过，才再次冻结并从头重跑全部正式内容。`boundaries-1/2` 等开发诊断不是冻结验收；源码变动期间运行的诊断只作开发记录保留。正式运行重新执行全部边界并核对前后哈希。

## 6. 冻结与复现

最终受测实现提交 `d4d7afd436bab076c180efc44832579b36932033`；源码、测试、脚本、仿真资源、配置和pyproject的冻结SHA-256为 `239f09bff8d456a87f7f32b3b86140562c95b417cf4480147bfb4804e8f61986`。两次冻结时工作区均干净。原 `frozen.json` 与失败 `acceptance-1/` 保留，最终记录为 `artifacts/phase3-round3/frozen-2.json`。

```bash
.venv-migration/bin/python -m unittest discover -s tests -v
VAF_SIMULATION_SITL_BIN_DIR="$PWD/artifacts/phase2-control/ardupilot-source/build/sitl/bin" \
  .venv-migration/bin/python -m tests.simulation.round3_boundaries \
  --run-dir artifacts/phase3-round3/boundary-UNIQUE
./scripts/test_phase3_actions.sh --allow-send \
  --sitl-bin-dir artifacts/phase2-control/ardupilot-source/build/sitl/bin \
  --run-dir artifacts/phase3-round3/acceptance-UNIQUE
```

详细部署、生命周期和恢复合同见 [ROUND3_LIFECYCLE_AND_IDENTITY.md](phase3/ROUND3_LIFECYCLE_AND_IDENTITY.md)。原P1 action_ownership/durable、ROS worker结果映射、VehicleActionDriver、车辆、Execution/Authority/Safety、SimulationRuntime、车型模型/物理参数与安全阈值均不修改。普通release、删文件、新目录、换scope都不是未知作业恢复路径。

### 6.1 首次正式回归发现的直接终态分类缺陷

候选 `1f2896532d0a4254538a309628ba15cc77e93d30` 的新旧边界、第一轮Rover/Chrome及Copter正常场景通过，但Copter故障场景的1.2s SetVelocity期限用例FAIL。最后一条普通Twist在期限边缘被安全拒绝（invalid_effect_time，无command ID、未进入Writer），StopMotion实际COMPLETED，独立Driver已确认停止。Exit因旧普通Effect被拒绝而抛stop_exit_unconfirmed，manager却无条件将原TIMED_OUT改成FAILED，违反既有终态断言。原始证据见 `acceptance-1/` 和 `deadline-analysis.json`，不改写该次FAIL。

新增确定性正反对照先复现FAILED覆盖TIMED_OUT，再最小修改manager：退出异常时保留已发生的TIMED_OUT作为逻辑原因；所有独立安全判定照旧，Driver/外部作业不安全仍UNKNOWN/保留，绝不变成成功。测试核查过期后没有新增Effect/写调用，安全未证明时资源不能释放。修复前后为 `deadline-before.log` / `deadline-after.log`，随后真实Copter故障入口原断言通过。该单独诊断未冻结且只读使用本机已有Copter二进制，状态/凭据仍全部置于新自有目录；没有写入独立ArduPilot项目。最终正式验收全部显式使用项目内隔离SITL二进制。

补修提交 `d4d7afd436bab076c180efc44832579b36932033` 只改这条manager条件及对应单元测试，没有修改停止/物理/Safety/TTL阈值或既有断言。最终全部正式内容重新运行，不以单独诊断代替两轮验收。

## 7. 冻结后的正式结果：READY FOR RE-AUDIT

受测提交 `d4d7afd436bab076c180efc44832579b36932033`。UTC：2026-10-25T12:30:11.016641+00:00 至 2026-10-25T13:44:23.633742+00:00。源码/测试/脚本/仿真输入前后摘要均为 `239f09bff8d456a87f7f32b3b86140562c95b417cf4480147bfb4804e8f61986`。[原始汇总](../artifacts/phase3-round3/acceptance-2/summary.json)。

全量501项单元，零失败、零错误、零跳过；原Phase1/2入口再次运行同一全量单元，也通过。两项新边界和保留的真实ROS/API边界先全部通过，再执行完整长回归。

| 轮次 | Rover正常/故障 | Copter正常/故障 | Plane正常/故障 | Chrome闭环 | 外部接口 | A–G |
|---|---|---|---|---|---|---|
| 1 | 通过/通过 | 通过/通过 | 通过/通过 | 真实浏览器通过 | 11项通过 | 全通过 |
| 2 | 通过/通过 | 通过/通过 | 通过/通过 | 真实浏览器通过 | 11项通过 | 全通过 |

两轮三车型Action真实场景共12个，原Phase1/2完整真实场景18个，另有新的两组混合Rover边界，合计32个正式自有SITL/Gazebo fixture。物理结果继续使用独立Gazebo真值；没有把ACK等同到达或着陆。两轮Chrome包含执行、刷新同实例、取消和停车。

原功能回归：[原始汇总](../artifacts/phase3-round3/acceptance-2/phase2-regression/summary.json)。

| 原回归轮次 | Rover A–F | Copter A–F | Plane A–F |
|---|---|---|---|
| run-1-6f88773d | 全通过 | 全通过 | 全通过 |
| run-2-d719731f | 全通过 | 全通过 | 全通过 |

### 7.1 Provider A–K 实测

[原始汇总](../artifacts/phase3-round3/acceptance-2/round3-boundaries/summary.json)。数字来自真实服务端已启动/活跃Job和独立应用快照，非配置值。

| 项 | 实际结果 |
|---|---|
| A：同Provider的目录/scope组合 | 新请求REJECTED，服务端实际总启动=1、活跃=1 |
| B：同Provider的目录/scope组合 | 新请求REJECTED，服务端实际总启动=1、活跃=1 |
| C：同Provider的目录/scope组合 | 新请求REJECTED，服务端实际总启动=1、活跃=1 |
| D：同Provider的目录/scope组合 | 新请求REJECTED，服务端实际总启动=1、活跃=1 |
| E：两份真实空闲证明 | 两次确为空闲；第二ledger注册被程序拒绝；尚未启动Job |
| F：SIGKILL/新别名/UUID/scope | 旧作业仍运行；三种接管尝试均拒绝，实际活跃仍1 |
| G：服务已启动、Job ID未返回 | 4个独立应用；活跃竞争/重启均REJECTED，对账前实际Job=1，完整可信inventory后新Job=SUCCEEDED |
| H：同时注册并申请 | 两个独立应用同时放行，成功owner=1、实际启动=1、活跃=1 |
| I：损坏/丢失/短写 | 4种真实记录损坏/缺失均阻挡新增Job；短写时实际启动=0；恢复原未解决记录后，对新鲜Provider正常重试=SUCCEEDED |
| J：真正不同Provider | 实际身份不同，两边各1个活跃Job，合法并发成立 |
| K：可信终态恢复 | 既有Job GET确认终态后解除；新Job=SUCCEEDED，总启动=2、当前活跃=0 |

未解决的同一独占Provider资源在这些场景中始终只有一个真实活跃作业。第二目录没有因真实空闲证明就取得独立协调身份；普通scope没有成为新隔离域。

### 7.2 真实混合Action正反对照

| 场景 | 车辆/外部证据 | 结果 |
|---|---|---|
| hybrid_unsent_exception | 车辆实际Effect=0、取消前Writer=0；真实Driver已安全=True，外部仍活跃1 | UNKNOWN且共同资源保留；同Runtime/独立alias均REJECTED；可信终态后仍保留UNKNOWN历史，正常新Action=SUCCEEDED |
| hybrid_actual_effect_timeout | 车辆实际Effect=1、取消前Writer=1；真实Driver已安全=True，外部仍活跃1 | UNKNOWN且共同资源保留；同Runtime/独立alias均REJECTED；可信终态后仍保留UNKNOWN历史，正常新Action=SUCCEEDED |

实际车辆Effect为静止HOLD模式命令，未解锁移动；该混合边界只验证真实Driver责任组合，不冒称运动验收。后续两轮完整三车型场景另外验证实际运动、起飞、返航、着陆。原始Writer字节记录在各混合summary/runtime中。

原真实ROS提交后结果丢失/API已知及未知Job ID重启回归：[原始汇总](../artifacts/phase3-round3/acceptance-2/independent-remediation-boundaries/summary.json)，三组全通过。真实Service已开始后客户端异常仍UNKNOWN，占用保留、冲突不启动、Query可用；精确同次终态oracle后新成功/实际错误/未提交不可用正常结束。旧水位独立16组重跑：[原始汇总](../artifacts/phase3-round3/watermark-recheck/watermark_probe.json)。

### 7.3 正常控制与故障物理对照

| 轮次/车型 | 实测摘要 |
|---|---|
| 1/rover | Goto误差0.1941m；浏览器刷新同实例=True；取消后速度0.001288m/s；未知交接Writer=0 |
| 1/copter | ENU位移1.1407m、FLU投影1.1304m；Takeoff/Goto/Land/返航实际通过；未知交接Writer=0 |
| 1/plane | 滑跑19样本、爬升51.6596m；实际AutoLand；故障ACK丢弃1、转发0、应用收到0，实际TAKEOFF Writer=1；未知交接Writer=0 |
| 2/rover | Goto误差0.2249m；浏览器刷新同实例=True；取消后速度0.001210m/s；未知交接Writer=0 |
| 2/copter | ENU位移1.1260m、FLU投影1.1565m；Takeoff/Goto/Land/返航实际通过；未知交接Writer=0 |
| 2/plane | 滑跑19样本、爬升51.6608m；实际AutoLand；故障ACK丢弃1、转发0、应用收到0，实际TAKEOFF Writer=1；未知交接Writer=0 |

正常签名确认、连续Arm/Disarm、车辆安全退出和纯外部正常完成均工作；未靠拒绝所有确认、取消所有请求或永久锁死资源取得结果。原回绕重放、Writer锁/Guard/Lease期限零写、会话/重连、旧队列和UNCONFIRMED回归继续通过，门槛不变。

## 8. Wheel、历史完整性与清理

新wheel在全新非editable venv安装并实际运行CLI及真实ROS/DDS Action：[原始汇总](../artifacts/phase3-round3/wheel-check-2/summary.json)。216个Python模块、44个运行配置/资源、6个Web静态文件逐字节匹配；18项catalog，默认无车辆/关闭SEND，主应用无rclpy导入；managed provider正常释放。wheel SHA-256 `2fc051c7fe7d0d466fc738422fb34f9f3dbcf71a65101aaa01ad7175599d781b`。

既有ROS测试server收到SIGTERM后的重复shutdown诊断仍如实保留（含wheel/外部server原始stderr），不把该退出噪声当功能通过证据；真实任务结果已返回且实际进程/端口均退出。未扩大范围重构这个旧fixture。

[原始汇总](../artifacts/phase3-round3/delivery-audit.json)：本轮46个实际自有fixture全部清理，其中32个正式fixture；PID/start_ticks对应进程均不存活，记录端口可重新绑定，相关API/ROS/worker扫描无残留。注册临时密钥、*.private、EEPROM和SITL state均已销毁。38份原始帧日志未保留SETUP_SIGNING。没有解析EEPROM密钥或在报告/Git输出认证密钥。

2052项历史保护文件、第一轮58项和第二轮61项独立原件/归档哈希均保持一致；更早739项也再次核验。旧报告、失败目录和既有正常仿真证据不改写。已销毁凭据的历史二进制仍按原记录unavailable，不伪造其原哈希可复验性。

外部UNKNOWN reservation作为非敏感记录保留，shutdown不强行清空；测试只处理明确拥有的provider、文件和进程。独立ArduPilot/插件项目没有源码修改。所有本轮原始材料位于`artifacts/phase3-round3/`，完整索引：[round3-remediation-evidence.json](phase3/round3-remediation-evidence.json)。

## 9. 提交、限制和交付

受测实现提交 `d4d7afd436bab076c180efc44832579b36932033`；包含两个P2修复、直接必要依赖、12项新增单元和真实边界入口。正式运行前后源摘要一致。最终README、报告和新证据索引另作纯文档提交，最终SHA与提交后工作区记录见[交付状态](../artifacts/phase3-round3/delivery-state.json)、Git日志和交付消息；提交后记录不放进自引用索引。

限制：同一受信OS账户/固定本机注册根、诚实Provider身份与终态、可靠本地rename/fsync；不提供跨主机全局协调、恶意Python隔离或通用ROS Trigger状态查询。原无可信证据的UNKNOWN必须保留；缺失/损坏/新epoch不自动重置占用。具体合同和受控恢复见第6节链接。旧ROS测试server退出诊断如第8节所述，无未解决的本轮P1/P2或强制测试失败。

开发侧最终状态 **READY FOR RE-AUDIT**。保留两次独立FAIL及原水位/ROS复审通过结论，等待第三轮独立复审；不自行宣布Phase3 PASS，完成后停止，不进入Phase4。
