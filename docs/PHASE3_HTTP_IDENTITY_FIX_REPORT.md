# Phase 3 HTTP 作业身份修复（R3-P2-A）

开发侧状态：**READY FOR RE-AUDIT**。本次修复第三轮独立 FAIL 发现的 R3-P2-A，
不改写该次结论，不宣布 Phase 3 冻结，不进入 Phase 4，不连接实车。

## 基线与修复前证据

基线 HEAD `07c1d173f73a8638909ae2a3d5f545717f4f2b76`，工作区起初干净；
其受测实现为 `d4d7afd436bab076c180efc44832579b36932033`。
原第三轮独立报告 `/tmp/vaf-phase3-third-review-43R0M7Y0/INDEPENDENT_PHASE3_THIRD_REVIEW.md`
保留，另原样复制进本次证据目录。原报告、程序、结果及之前的失败材料均未修改。

修改前将独立 epoch 探针复制到新的 `before/` 目录重跑，两条路径均再次复现：
普通轮询误报 SUCCEEDED，UNKNOWN 后自动对账把 release_safe 改为 true；
两者均清空占用，而旧 Provider Job1 仍运行。恢复旧 endpoint 后，同一 Registry/
Ledger/scope 又启动 Job2，实际同时 RUNNING=2。手工恢复正确拒绝身份不匹配。
见本次证据 `before.log`、`before/epoch-probe.json`、`before/epoch-requests.json`。

根因在 `ApiJob`：只在构造时验证身份；正常轮询及后台 `query_existing` 只按
endpoint/Job ID 读取状态，未证明终态属于启动时的 Provider/epoch。

## 修改

- ApiJob 固定启动时的 provider_id/provider_epoch/resource_id，并写入恢复描述。
- HTTP v2 的 `/identity` 显式声明 `X-VAF-Job-Protocol: 2`；旧接口在提交前拒绝。
- 每个作业请求携带 `X-VAF-Expected-Provider`。Provider 必须在副作用之前比较
  真实身份；校验与副作用处于同一 Provider epoch，切换后不能处理旧 epoch 请求。
- 每个作业响应携带真实 `provider`；状态/取消响应还携带匹配的 `job_id`。
  普通轮询、取消、自动对账和手工对账使用相同校验规则，不再依赖单独 GET identity
  与后续 GET 之间的时间窗口。错误/缺失身份或 Job ID 不能成为安全释放证据。
- 身份异常后保持 UNKNOWN/占用，不自动重提 POST。恢复旧 endpoint 时若旧作业
  仍运行，继续占用；只有其自身可信终态或受控完整 inventory 才能恢复。
- 已验证终态不被迟到的 RUNNING/错误状态覆盖。旧 UNKNOWN 历史不改成成功。
- 旧恢复描述若没有内嵌身份，手工恢复只能使用持久 reservation 已固定的身份，
  仍要求 v2 响应。没有 endpoint/Job ID 单独认领终态的回退路径。

协议及响应例子见 [外部合同](phase3/EXTERNAL_ACTIONS.md#http-job-protocol-v2)。
本仓库交付的是客户端和自有测试 Provider，不声称提供生产 HTTP 服务端。
外部部署必须升级 Provider；不支持 v2 的已有未知作业需要可信部署对账，不能
删除 Ledger、换 scope 或新建空目录绕过旧占用。

改动限于 HTTP 客户端、手工恢复装配、必要的测试 Provider/新边界与合同说明。
Vehicle、Execution、Authority、Safety、唯一 MAVLink Writer、双 SEND、Lease、TTL、
Session/Generation fences、停止/飞行物理阈值及 ROS worker 结果映射未改。

## 验证

在此前独立审查新建并已按仓库要求安装 `.[mavlink]` 和 vision 依赖的隔离 venv 中执行。
本次实际受测源码/测试/脚本/配置/仿真输入摘要：

`f28beeca74f9ba209506e7b59d60c5d8f96e0802708712c9b24862d72eb09794`

| 检查 | 结果 |
|---|---|
| 全量 unittest discover | 512 项通过，70.605s，零失败/错误/跳过 |
| 新 HTTP 身份矩阵 | 11 项真实 HTTP/Provider/转发入口边界通过 |
| 原 Provider A–K | 真实多进程、存活竞争、SIGKILL、丢失ID、损坏/短写、不同Provider并行和可信恢复全部通过 |
| 两组真实 Rover 混合边界 | 未发车辆Effect+Exit异常、实际HOLD Effect+Exit超时均通过；未修改VehicleActionDriver |
| 原 ROS/API 恢复边界 | 真实DDS Service提交后异常、HTTP已知/未知ID跨进程恢复3组通过 |
| Native/API/ROS常规集成 | 1轮11项通过，含成功、反馈、错误、取消、超时、不可用及UNKNOWN |
| 完整两轮正式长回归/新Chrome/wheel | 本次未重跑；原正式结果只作历史材料，不能当作新受测提交的完整验收 |

新 HTTP 矩阵覆盖：普通轮询换 epoch、UNKNOWN 自动恢复换 epoch、identity 与 GET
之间切换、真实异代终态响应、取消时切换、POST前切换、同epoch错误Job ID、缺失
provider、缺失job_id、服务已启动但创建响应身份丢失，以及不支持v2。

所有适用负例的竞争 Action 均 REJECTED，旧 Job 仍运行时资源保留；另一个 epoch
的历史 Job 没有被取消。每组恢复后都运行新 Action SUCCEEDED，原 Provider 同时
活跃数峰值不超过1。POST前换epoch时实际启动0；创建响应身份丢失时实际启动1、
本地Job ID未知，阻止自动重提，可信完整inventory后才恢复。测试不以全拒绝或永久
占用取得通过。

新入口已加入正式 `test_phase3_actions.sh` 的先行边界阶段；原阶段、断言及物理
阈值保留。初次新单元夹具因临时目录已存在而失败，仅修正测试输出子目录，原日志
保留；随后11项定向和512项全量通过，没有把夹具失败算成产品失败或隐藏测试。

复现入口：

```bash
python -m unittest discover -s tests -v
python -m tests.simulation.http_job_identity --run-dir <新隔离目录>
VAF_SIMULATION_SITL_BIN_DIR="$PWD/artifacts/phase2-control/ardupilot-source/build/sitl/bin" \
  python -m tests.simulation.round3_boundaries --run-dir <新隔离目录>
python -m tests.simulation.remediation_external --run-dir <新隔离目录>
python -m tests.simulation.external_actions --run-dir <新隔离目录>
```

## 证据、清理与限制

新证据归档：`artifacts/phase3-round3/http-identity-fix-JNj27EOj/`；原运行目录
`/tmp/vaf-phase3-epoch-fix-JNj27EOj/` 保留。大小/哈希见
[证据索引](phase3/http-identity-fix-evidence.json)。提交SHA在交付消息和Git日志中给出，
避免在同一提交的报告中自引用。

核对本轮历史证据索引1461项和保护集合2052项均哈希不变。两个新自有Rover fixture
的临时认证材料、SITL state和PID/start_ticks对应进程均已清理；22个已记录HTTP端口
可重新绑定。新HTTP Provider线程全部关闭，未知reservation作为非敏感证据保留。

范围仍为受信本机OS账户、共享固定Registry、诚实Provider身份与终态、可靠本地
rename/fsync。v2协议不是跨主机分布式锁或恶意Python沙箱，也不构成实车部署认证。
本次开发侧定向验证通过，仍待独立复审及新受测提交的完整正式验收。
