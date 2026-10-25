# Phase 3 标准 Action 能力系统开发报告

> 状态及正式运行结果由本报告末尾的冻结提交验收记录给出。开发侧结果须交独立审查，不表示最终阶段验收通过。

## 1. 基线与范围

分支 `feat/phase3-action-system` 从干净的 `1d6de8296e4b727bbc74aabc42bdbfacb1e63902` 创建。原 Phase 2 生产控制基线为 `634c30b02bc7f7b94030e14c2899f3abd375c716`。进入本阶段前，ACK 丢弃参数缺陷已在 `561e1785079eb1b678f1ac22463d6b0e7c8a2610` 修复并完成两次真实 Plane Cancel Window 复核，记录见 [Phase 2 P3 报告](PHASE2_P3_ACK_INJECTION_REPORT.md)。原 CONDITIONAL PASS、FAIL 与修复记录均保留，未改写为无保留 PASS。

基线全量测试为 420 项通过。现有七模块和旧 Mission 执行路径保留。本阶段增加独立 Action 实例管理、三车型标准库、外部服务合同和 Web Action Lab；未开发 Mission Graph、AI 决策、Nav2 导航、SLAM 算法、视觉算法或实机控制。原有其他阶段名称如 P1–P25 是历史工程记录，不是本轮提前开发后续 Phase 的声明。

环境为隔离 Python 3.12.3、pymavlink 2.4.49、Gazebo Sim 8.15.0，以及项目自有构建目录中的三车型 SITL。ArduPilot 源版本 `b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`，Gazebo 插件版本 `3ec51428fd43deb7b71137192ba16394b450d78e`；实际二进制、参数与插件库哈希逐场景保存在 manifest。外部 ArduPilot 源和已有插件资源只读使用，没有删除或修改独立项目；插件目录已有非本轮未跟踪资源，不宣称整台主机工作区干净。

## 2. 实现与依赖边界

`contracts/action.py` 定义四种运行语义、统一状态、共享/独占资源、不可变目标上下文和独立安全结果。原 `ActionSpec` 保留兼容字段，增补版本、参数/输出 Schema、车型与能力、所需状态、新鲜度、资源、超时、Effect TTL、实现引用和成功/取消说明。旧 Mission 注册器与基本 Action 继续使用原接口。

Registry 为 Web/API 和执行器的唯一元数据来源。冻结 dataclass 生成严格 JSON Schema；未知字段、非有限数、把布尔值当数值、缺失必填参数和越界参数均拒绝。注册器处理版本、重复名称、车型/能力过滤，输出每车型参数差异与结果结构。机器目录见 [action-catalog.json](phase3/action-catalog.json)，完整使用方式见 [USAGE.md](phase3/USAGE.md)。

`engine/action/manager.py` 是唯一新增的通用 Action Runtime，不导入 Web、ROS、MAVLink 或具体车型。OneShot、Goal、Continuous、Query 共用同一状态机：创建、校验、资源等待、运行、取消，以及 SUCCEEDED/FAILED/REJECTED/CANCELLED/TIMED_OUT/UNKNOWN。回调只接收不可变 WorldSnapshot 和只读 Command 结果，产生 Typed Effect 请求。运行结果还需通过输出 Schema 校验。

运行中的 Continuous 不能因提供者自行结束而假报成功。取消/超时先进入有界退出，物理结果不确定时以 UNKNOWN 结束并保留资源。异常、远端调用失联、取消异常或无法证明无副作用的准入失败不能自动释放资源。只有明确的无副作用拒绝或已完成安全退出可以释放。实例、反馈、历史和 Effect 都有预算；记录耗尽会拒绝新任务，不驱逐危险占用。

写 Action 在每个目标上独占 `vehicle.control` 冲突组，覆盖 arm/mode/motion，和现有唯一控制 Lease 对齐；Query 共享 `vehicle.state`。可并存多个实例、跨目标独立运行、同目标读取与运动并发，冲突可拒绝或有限等待，等待可以取消。此处不是 Mission Parallel 编排。通用 Runtime 不持有车辆命令端口。

应用装配 `VehicleActionDriver` 以每车一个独立 owner 线程驱动原 SimulationRuntime，通过现有公开 begin_run/dispatch_envelope/cancel_pending/end_run 接口工作。车辆控制仍为：

```text
Web/API → Action Runtime → Typed Effect → VehicleActionDriver
        → 原 Execution / Authority / Safety
        → 原 Vehicle / Protocol / Transport / 唯一 MAVLink Writer
        → ArduPilot SITL → Gazebo
```

Query 不创建或撤销运动授权。Effect 的结果固定保留原发送 Session，不能被后续重连的 Session 冒名。owner 在完整调度周期后发布 Command 结果，避免把内部暂态 ACCEPTED 切片暴露为完成稳定窗口的重置事件。

遥测 TCP 切片可能短暂缺少姿态或位置。初次校验在有限时间内等待完整新鲜状态，不提前授予控制权；运行中等待时不产生运动 Effect，按最后完整状态的原采样时间计算上限，不借其他新遥测延长有效期。已有独立 deadman、周期期限和 Writer 最终检查仍生效。过期、未来、错误时域或无效质量直接失败。完整状态等待规则有确定性和真实回归证据。

## 3. 标准 Action 清单及结果语义

共 18 个名称、31 个车型绑定，版本 1.0.0。所有写操作还要求明确自有 SITL、双 SEND、Lease、Session/Generation、TTL 和 Safety。表内简写的参数/输出详见机器 Schema；不是额外的前端参数清单。

| Action | 车型 / 类型 | 输入与输出 | 成功条件 | 取消、超时与故障 |
|---|---|---|---|---|
| GetVehicleState | 三车型 / Query | 无；返回 WorldSnapshot、时间/质量、home、context、read_only | 返回只读快照，不要求授予运动权限 | 无车辆副作用，不撤销并发控制 |
| SetMode | 三车型 / OneShot | mode；confirmed、physical_arrival_claim=false | Command COMPLETED 与认证的新目标模式状态 | 未确认写入结果保留 UNKNOWN；模式确认不代表物理完成 |
| Arm | 三车型 / OneShot | 无；confirmed、physical_arrival_claim=false | 原 Command 确认链与实际 armed 状态 | 不确定保留资源；不使用 force arm |
| Disarm | 三车型 / OneShot | 无；confirmed、physical_arrival_claim=false | 原 Command 确认链与实际 disarmed 状态 | Copter/Plane 必须有本 owner 完成 Arm 的签名地面参考和静止状态，禁止空中 Disarm |
| Drive | Rover / Continuous | speed_mps ±0.5；无成功结果 | 持续运行，不能自行成功 | 旧流零速后原生 HOLD，使用原停车证据窗口；后续运动显式 GUIDED |
| Turn | Rover / Continuous | yaw_rate_rad_s ±0.35；无成功结果 | 持续运行，保留正反原地转向 | 同 Drive；无确认停车保持 UNKNOWN |
| Goto | Rover/Copter / Goal | odom x/y；Rover z=0，Copter z≤2；physical_goal_observed | 复用原 BasicAction 的空间误差、稳定与退出停车屏障 | 原零速/停止屏障；故障保留不确定资源 |
| Stop | Rover / Goal | 无；physical_goal_observed | 实际静止与完成的原停止屏障 | 停车未确认不能交接控制 |
| Takeoff | Copter/Plane / Goal | Copter height≤2；Plane 固定已校验 50m；physical_goal_observed | Copter 原高度 ±0.35m 稳定2s；Plane 50±5m、8..28m/s 稳定2s | Plane 不能零速停车；起飞成功仍保留飞行占用 |
| SetVelocity | Copter / Continuous | ENU odom 或 FLU base_link，vx/vy ±0.5、vz ±0.3、yaw_rate ±0.35；无成功结果 | 持续运行，复用既有转换与执行边界 | 取消经原运动停止屏障；不确定保留资源 |
| SetYaw | Copter / Goal | yaw_rad ±π；返回 yaw_rad | 实测航向误差≤0.1rad、稳定1s | 同 Copter 停止屏障 |
| Hold | Copter / Continuous | 无；无成功结果 | 持续保持，不假报终态成功 | 原停止屏障，UNKNOWN 不释放 |
| ReturnHome | Rover/Copter / Goal | 无；physical_goal_observed、armed | Rover 到 home≤0.75m、速度≤0.1m/s 稳定2s及 HOLD；Copter home≤0.75m、着地且解除武装 | 真实车辆状态证据；原生返航未确认不可安全交接 |
| RTL | 三车型 / Goal，成功语义按车型明确 | 无；R/C 为物理目标结果，Plane 为配置确认 | Rover/Copter 与 ReturnHome 相同；Plane 只确认原生 RTL 配置，physical_arrival_claim=false | Plane 续飞占用不释放；不将 RTL ACK 当返航着陆完成 |
| Land | Copter / Goal | 无；physical_goal_observed | 原着地、低速、解除武装和稳定要求 | 原停止/退出逻辑；ACK 不等于着陆 |
| SetGuidedTarget | Plane / OneShot | 经纬度、显式 AMSL；confirmed、physical_arrival_claim=false | 原生目标 Command 与 GUIDED 配置确认 | 不宣称实际到达；保留飞行占用 |
| Loiter | Plane / OneShot | 无；confirmed、physical_arrival_claim=false | 认证原生 LOITER 模式确认 | 保留飞行占用，不宣称悬停或停止 |
| AutoLand | Plane / Goal | 无；physical_goal_observed、armed=false | 相对本次 Arm 地面高度<0.25m、速度<1m/s 稳定3s，再观察认证解除武装 | 不满足地面证据时绝不空中 Disarm；不确定保留飞行占用 |

常规 SetMode 不开放 Rover RTL、Copter RTL/LAND、Plane TAKEOFF/AUTOLAND，要求使用相应带物理完成条件的 Action。Plane 原生配置操作的成功只能表示配置确认。Rover/Copter 第1轮使用 ReturnHome，第2轮使用 RTL，覆盖两个公开名称。每个名称的真实实例、参数、Action/Command 结果和状态历史按场景保存在 summary 与 runtime.jsonl；逐项验收索引见本报告后面的正式运行结果。

Plane 的成功飞行操作保留资源和原生 flight scope；只有指定成功占用实例的 `continuation_of` 并给予新的显式 SEND，才能触发既有 LOITER 回收、旧队列隔离、权限撤销、只读新 Session、新鲜全球定位/飞行状态确认和重新授权。失败、取消或 UNKNOWN 不能使用此续接路径。取消仍是 UNCONFIRMED；没有采用空中 Disarm、零速度或自动任务级抢占。

## 4. 外部能力与 Web Action Lab

外部统一 Job 合同支持 poll/feedback/result/cancel/close。本地 NativeJob 用合作式取消；ApiJob 用明确部署的 job API；ProcessJob 为可选 ROS worker 提供有界进程协议。未知远端结果、取消异常及无句柄准入异常保持 UNKNOWN 和资源占用。此合同不要求外部算法经过车辆 Execution；若要运动，仍须独立发出经过授权的 Typed Effect。

本机真实 ROS 2 Jazzy 已使用独立进程、专用 domain、UUID namespace 和 localhost DDS 验证。实际 `nav2_msgs/action/Wait` ActionServer/Client 与 `std_srvs/Trigger` 验证 Goal、Feedback、Result、Cancel、Timeout、不可用、错误和断连 UNKNOWN。主应用不导入 rclpy。每轮外部集成 11 个场景同时覆盖原生任务、API 成功/错误和 Continuous API 取消。Wait 仅用标准消息与本地定时服务器，不构成 Nav2 导航实现，详见 [外部合同](phase3/EXTERNAL_ACTIONS.md)。

Web Action Lab 的参数表单直接由 Registry 生成。可查看车型能力、连接和授权、实例反馈/结果/命令、日志及资源，运行与取消单个 Action。循环调度独立于 HTTP/浏览器；刷新后通过原实例 ID 继续管理。采用既有 loopback、Bearer、CSRF、Origin/Host 与幂等请求约束。CLI `vehicle-autonomy-actions` 默认无车辆、SEND 关闭；显式自有 manifest 与 deployment SEND 之外，每次写 Action 还需自己的 SEND。

每轮使用真实 headless Chrome 经 UI 执行 SetMode、Arm、Drive、刷新重连、取消；独立 Gazebo 证据同时检查位移和停车速度，截图遮盖令牌。其余全部车型 Action 也经过真实认证 HTTP API；Web 不直接发 MAVLink、不推测完成结果。

## 5. 安全合同与使用限制

- 未修改旧 Execution、Authority、Safety、Vehicle/Protocol/Transport 或 BasicAction 控制实现。原双 SEND 默认 false、唯一 Writer、Lease/TTL/Deadline、Session/Generation fences、Guards 和未知停车规则保留；测试实际检查 Writer 次数及真实帧，不以 Action 标签代替物理证据。
- 启动只接受有明确进程/目录/端口/二进制与资源身份的自有 loopback SITL manifest。每个 fixture 用 OS 文件锁限制一个 Action owner；没有实机、串口、任意外部飞控或硬件 controlled 接口。HardwareReadOnly 不变。
- 每条下行确认仍要求实际验证 MAC 与严格签名时间戳水位。8位 packet sequence 不是请求 UUID，签名顺序也不提供任意网络攻击下的唯一命令关联。保留 Phase 1 对协议歧义的限制，不宣称绝对抗重放。
- 应用重启跨同一签名 epoch 的接收水位持久化采用先写后接受、最多128个时间戳增量的保守预留，实时仍逐包验证。新 owner 可能暂时拒绝预留范围内的数据，但绝不降低水位；损坏文件拒绝控制。该机制信任同一 OS 的部署文件与进程身份，不防同权限用户篡改或密钥泄露。
- 新 owner 不接管已解锁且旧 scope 未解决的车辆；需要新鲜、解除武装、静止的地面初态或新建自有 fixture。未确认物理安全不能通过进程重启、Query 或一般成功标签清除危险。
- home/ground 来自本 owner 完成 Arm 后的签名位置，符合本次 AP 未锁定 home 的仿真约定；重 Arm 重新记录，不当作通用地形估计。物理验收另用 Gazebo 真值。
- Runtime 记录有界（默认128、Lab512实例，单实例2048 Effects、有限反馈/历史）；达到预算显式拒绝，需要操作员管理新运行，不能无限累积或静默丢弃危险占用。Action tick/exit 回调必须短时非阻塞，耗时原生/ROS/API 工作使用外部 worker。
- 外部 DDS 示例信任本地隔离服务器，namespace/domain 不是 DDS 认证。以上仅为所测本地仿真和软件合同证据，不代表真实车辆安全验收。

## 6. 开发中失败与修复记录

历史运行目录全部保留，不将下列记录混入最终正式通过结果。

| 原始记录 | 观察到的问题 | 修复/处理 |
|---|---|---|
| smoke-rover-1/2 | GZ 改写 argv 为 joined proctitle，身份验证拒绝；未写车辆指令 | 验证实际完整 GZ 命令身份，不放开所有权限制 |
| smoke-rover-3/4 | translator 装配参数错误 | 使用原 ArduRover translator 正确构造，无控制器修改 |
| smoke-rover-5 | 原动作稳定窗口被调度中间态 ACCEPTED 反复重置 | owner 在完整周期后发布结果 |
| smoke-copter-1 | LAND 后直接重 Arm 被 AP 拒绝 | 场景显式再次 GUIDED，保留 AP 拒绝条件 |
| smoke-plane-1 | 新 Session 尚无 global fix 即续接 | 等待真实完整新鲜状态再授权 |
| smoke-plane-2 | 使用世界绝对 z 而非 Arm 地面参考判断着陆 | 使用明确地面相对高度，保留0.25m门槛 |
| smoke-plane-3 | 每包 fsync 干扰原安全循环期限 | 持久化保守时间戳预留，保留逐包 MAC/水位及原循环期限 |
| browser-rover-smoke-1/2 | 隐藏 option 定位与退出时 Guided 速度衰减未满足停车期限 | UI 等待 attached；Rover 经原生 HOLD 回收，保留原8s/0.1m/s/2s停车要求 |
| acceptance-2faceb3-1、acceptance-final-1 | 开发侧主动中止以补齐逐 Action 独立真值、严格 SEND、输出 Schema 和 Session 溯源 | 原中止记录保留，不作为正式完整通过 |
| acceptance-complete-1 | 短暂不完整遥测切片导致立即 FAILED | 有界完整状态等待；期间不发运动 Effect，独立 deadman/Writer 不变 |
| acceptance-coherent-1 | Phase 3 两轮 A–F 通过；旧回归第2轮 Plane 在期限前即断言 UNKNOWN，整轮 FAIL | 仅修正测试：第三次回绕之后继续调度，等待原命令超时和实际重放拒绝；保持原20s上限及全部拒绝、World、Writer断言 |

最后一项的原始失败保存在 `artifacts/phase3-actions/acceptance-coherent-1/phase2-regression/run-2-5f9f4041/plane-control/`。当时只有3次合法 Writer 调用（MANUAL、Arm、Disarm），Disarm 保持 TRANSMITTED、World 保持 armed，没有旧 ACK 错误确认；清理后因连接结束记录 UNKNOWN。原测试把报文回绕速度当成命令超时，第一次运行恰好跨过期限，第二次最后一次 cycle 检查尚未跨过5s。新增可控时钟回归使三次回绕在2.4s内发生并验证等待5s实际超时；也验证错误完成、旧 ACK 被接受或额外写入仍失败。修复提交只涉及测试，不更改生产控制和超时。

## 7. 复现与证据保护

在隔离环境安装 `.[mavlink,test-browser]` 与现有 vision 依赖，准备本机 Chrome 与真实 ROS 2 Jazzy。运行：

```bash
.venv-migration/bin/python -m unittest discover -s tests -v
./scripts/test_phase3_actions.sh --allow-send \
  --sitl-bin-dir artifacts/phase2-control/ardupilot-source/build/sitl/bin \
  --run-dir artifacts/phase3-actions/acceptance-UNIQUE
```

正式入口要求干净提交，固定源码与资源哈希；执行两轮 Action/API/Chrome/真实ROS/SITL/Gazebo，再执行两轮原 Phase 1/2 三车型回归，每轮9个真实场景。每个场景使用全新目录、端口、仿真 world/partition、SITL 状态和临时签名 epoch。测试结果、真实转发/丢弃/重放帧、应用接收帧、Action/Command、Writer、Gazebo 轨迹、日志和清理记录分别保留。

清理复用已有受审 OwnedCredentials：只处理有目录设备/inode所有权记录的临时 SITL 状态及私密 provision 文件。先停止自有进程，再覆盖/fsync/truncate/unlink。manifest 准确记载已销毁二进制的原哈希和 unavailable，绝不伪称二进制仍存在。没有重新暴露、记录或提交临时认证密钥。

基线保护索引为 `artifacts/phase3-actions/baseline.json`，包含739个历史证据文件的哈希。正式交付另附 [evidence.json](phase3/evidence.json)，记录本次非敏感证据的大小和哈希；原始大文件仍在忽略的 artifacts 目录，不提交虚构的替代证据。最终运行、清理、wheel、历史保护审计和 Git 状态见以下结果记录。

## 8. 冻结提交与正式两轮结果

最终开发侧状态：**READY FOR RE-AUDIT**。等待独立审查，不宣称最终 Phase 3 PASS。

受测提交：`047bebafaf7bdb6f1d44407606200810da4d80e0`。生产代码与先前 `5651edf09b2b36dd9f3b2225a670984f89e18377` 相同；最后提交仅修复回归测试的调度时序并增加确定性测试。

源码/测试/脚本/资源冻结 SHA-256：`d7c64b1e77e56c631a846556421cc2695f5bf50bdf39282088fcd5382651d000`，运行前后相同。运行 UTC：2026-10-25T03:17:39.820535+00:00 至 2026-10-25T04:29:37.335733+00:00。

正式总汇总：[summary](../artifacts/phase3-actions/acceptance-047beba-1/summary.json)；全量单元：[summary](../artifacts/phase3-actions/acceptance-047beba-1/unit.json)。共 466 项、零失败、零错误、零跳过。

| 轮次 | Rover 正常/故障 | Copter 正常/故障 | Plane 正常/故障 | 外部接口 | A–G | 原回归轮次 |
|---|---|---|---|---|---|---|
| 1 | 通过 / 通过 | 通过 / 通过 | 通过 / 通过 | 11项通过 | 全部通过 | `run-1-85769205` |
| 2 | 通过 / 通过 | 通过 / 通过 | 通过 / 通过 | 11项通过 | 全部通过 | `run-2-58b22294` |

### 8.1 每个公开 Action 的实际结果

同名操作的多次执行和预期冲突拒绝在原始 summary 中分别保留；下表列正常成功或 Continuous 取消路径。Rover/Copter ReturnHome 与 RTL 分轮覆盖。

| 车型 | Action | 轮次及实际终态 |
|---|---|---|
| copter | Arm | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| copter | Disarm | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| copter | GetVehicleState | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| copter | Goto | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| copter | Hold | 第1轮 CANCELLED；第2轮 CANCELLED |
| copter | Land | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| copter | RTL | 第2轮 SUCCEEDED |
| copter | ReturnHome | 第1轮 SUCCEEDED |
| copter | SetMode | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| copter | SetVelocity | 第1轮 CANCELLED；第2轮 CANCELLED |
| copter | SetYaw | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| copter | Takeoff | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| plane | Arm | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| plane | AutoLand | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| plane | Disarm | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| plane | GetVehicleState | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| plane | Loiter | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| plane | RTL | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| plane | SetGuidedTarget | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| plane | SetMode | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| plane | Takeoff | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| rover | Arm | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| rover | Disarm | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| rover | Drive | 第1轮 CANCELLED；第2轮 CANCELLED |
| rover | GetVehicleState | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| rover | Goto | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| rover | RTL | 第2轮 SUCCEEDED |
| rover | ReturnHome | 第1轮 SUCCEEDED |
| rover | SetMode | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| rover | Stop | 第1轮 SUCCEEDED；第2轮 SUCCEEDED |
| rover | Turn | 第1轮 CANCELLED；第2轮 CANCELLED |

### 8.2 独立 Gazebo 与浏览器观测

[两轮独立 Gazebo 轨迹、速度/高度图](phase3/trajectories.png)（由本次原始轨迹生成）。

| 轮次/车型 | 独立物理观测 | 原始证据 |
|---|---|---|
| 1 / rover | 前/后移 1.012167/1.027753m；正/反转 0.810158/0.809265rad；Goto 误差 0.179030m；Chrome 位移 0.237089m、取消后速度 0.001180m/s；刷新保持同实例=True，JS错误=0 | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-1-1212aa7f/rover-actions/summary.json) |
| 1 / copter | ENU 位移 1.162567m、速度 0.465169m/s；FLU 前向投影 1.168283m、速度 0.465906m/s；Land/返航实际着地解除武装 | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-1-1212aa7f/copter-actions/summary.json) |
| 1 / plane | 起飞爬升 51.658884m，地面滑跑 20样本、最大速度 18.774205m/s；原生目标误差 102.549929m、转角 2.113380rad、速度 10.116175m/s；AutoLand 实际着地稳定与解除武装 | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-1-1212aa7f/plane-actions/summary.json) |
| 2 / rover | 前/后移 1.024419/1.013947m；正/反转 0.798591/0.785686rad；Goto 误差 0.257785m；Chrome 位移 0.316112m、取消后速度 0.001417m/s；刷新保持同实例=True，JS错误=0 | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-2-4b74e39e/rover-actions/summary.json) |
| 2 / copter | ENU 位移 1.151268m、速度 0.465584m/s；FLU 前向投影 1.175667m、速度 0.466608m/s；Land/返航实际着地解除武装 | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-2-4b74e39e/copter-actions/summary.json) |
| 2 / plane | 起飞爬升 51.652750m，地面滑跑 20样本、最大速度 18.777058m/s；原生目标误差 102.608764m、转角 2.111985rad、速度 10.120898m/s；AutoLand 实际着地稳定与解除武装 | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-2-4b74e39e/plane-actions/summary.json) |

物理门槛保持原值：Rover 前后移动≥1m、正反转≥π/4；Goto/返航误差≤0.75m；Copter 速度位移≥0.6m、速度0.25..0.75m/s；Plane 有真实地面滑跑≥10m及速度>8m/s、爬升≥45m、目标误差≤120m且转角≥π/2、飞行速度8..28m/s；自动着陆原高度/速度/稳定与跑道门槛全部保留。没有将原生目标配置确认等同到达。

### 8.3 故障与实际 Writer / ACK 证据

| 轮次/车型 | 故障及实际边界 | 证据 |
|---|---|---|
| 1 / rover | 等待取消产生Effect数=0；正常超时确认停车后新有效运动可运行；旧HB重放 1次及遥测中断后UNKNOWN/UNCONFIRMED、资源保留；交接Writer 0次 | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-1-1212aa7f/rover-faults/summary.json) |
| 1 / copter | 等待取消产生Effect数=0；正常超时确认停车后新有效运动可运行；旧HB重放 1次及遥测中断后UNKNOWN/UNCONFIRMED、资源保留；交接Writer 0次 | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-1-1212aa7f/copter-faults/summary.json) |
| 1 / plane | 目标ACK实际丢弃 1、代理转发 0、应用收到 0；TAKEOFF实际Writer 1次；取消UNKNOWN/UNCONFIRMED、资源保留；后续交接Writer 0次 | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-1-1212aa7f/plane-faults/summary.json) |
| 2 / rover | 等待取消产生Effect数=0；正常超时确认停车后新有效运动可运行；旧HB重放 1次及遥测中断后UNKNOWN/UNCONFIRMED、资源保留；交接Writer 0次 | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-2-4b74e39e/rover-faults/summary.json) |
| 2 / copter | 等待取消产生Effect数=0；正常超时确认停车后新有效运动可运行；旧HB重放 1次及遥测中断后UNKNOWN/UNCONFIRMED、资源保留；交接Writer 0次 | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-2-4b74e39e/copter-faults/summary.json) |
| 2 / plane | 目标ACK实际丢弃 1、代理转发 0、应用收到 0；TAKEOFF实际Writer 1次；取消UNKNOWN/UNCONFIRMED、资源保留；后续交接Writer 0次 | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-2-4b74e39e/plane-faults/summary.json) |

ACK 丢弃同时检查代理 rx_discard、rx_forward 和 application-rx，绝非配置值推定。正常签名 ACK/HB 和连续 Arm/Disarm 的正例也必须通过，不能靠拒绝全部确认报文取得结果。原 Phase 1/2 回归另外覆盖三次完整序号回绕后的旧 ACK+HB、正常新证据、Writer 锁等待/Guard/Lease 过期零写、序号顺序、重连和全部原故障。

### 8.4 原 Phase 1/2 回归

[summary](../artifacts/phase3-actions/acceptance-047beba-1/phase2-regression/summary.json)：两轮9场景/轮、共18个真实 SITL/Gazebo 场景通过。原回归自身全量单元测试也通过。

| 回归轮次 | Rover A–F | Copter A–F | Plane A–F | 清理 |
|---|---|---|---|---|
| `run-1-85769205` | 全部通过 | 全部通过 | 全部通过 | 全部通过 |
| `run-2-58b22294` | 全部通过 | 全部通过 | 全部通过 | 全部通过 |

### 8.5 外部集成

| 轮次 | 真实集成用例与终态 | 证据 |
|---|---|---|
| 1 | native_goal: SUCCEEDED；api_goal: SUCCEEDED；api_cancel: CANCELLED；api_error: FAILED；ros_goal_feedback_result: SUCCEEDED；ros_cancel: CANCELLED；ros_timeout: TIMED_OUT；ros_error_result: FAILED；ros_unavailable: FAILED；ros_service: SUCCEEDED；ros_disconnect: UNKNOWN | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-1-1212aa7f/external/summary.json) |
| 2 | native_goal: SUCCEEDED；api_goal: SUCCEEDED；api_cancel: CANCELLED；api_error: FAILED；ros_goal_feedback_result: SUCCEEDED；ros_cancel: CANCELLED；ros_timeout: TIMED_OUT；ros_error_result: FAILED；ros_unavailable: FAILED；ros_service: SUCCEEDED；ros_disconnect: UNKNOWN | [summary](../artifacts/phase3-actions/acceptance-047beba-1/round-2-4b74e39e/external/summary.json) |

## 9. 安装、清理与历史证据审计

独立 wheel 含 213 个 Python 模块，逐字节匹配最终受测生产代码；最后测试提交未改变 wheel 内容。实际独立 venv 安装验证 entrypoint、静态资源、ROS wrapper、默认未连接/SEND关闭，以及安装后的 ROS worker 与真实 DDS ActionServer 的反馈/结果；主应用无 rclpy 导入。wheel SHA-256：`ce6c601480fdc2262e7a1a52f0a47da8d98ee7cd0f466edeb8156c9b09bffaf3`。证据 [summary](../artifacts/phase3-actions/wheel-audit.json)、[summary](../artifacts/phase3-actions/wheel-frozen-check/summary.json)。

最终审计 [summary](../artifacts/phase3-actions/delivery-audit.json)：30 个正式自有车辆 fixture 全部 credentials_removed、ports_released、remaining_process_groups=[]，无 sitl_state/私密 provision 文件残留，原PID/start-ticks核查无存活自有仿真进程。临时凭据二进制已销毁，manifest记录原哈希及不可用；不声称原二进制可恢复复核。

受保护的 739 个历史证据逐个哈希不变。190个基线Python模块中，仅原contracts/decision.py、engine/action/registry.py、engine/action/runtime.py有兼容扩展；原控制器及安全链字节不变。原测试只有 plane_regressions.py 修复上述等待缺陷，未删除、跳过用例或降低断言。旧失败证据全部保留。

补充环境审计见 [delivery-environment-audit.json](../artifacts/phase3-actions/delivery-environment-audit.json)：31个车型绑定的文档目录与实际Registry一致；38份原始帧日志中未保留SETUP_SIGNING凭据配置报文；整个Phase 3证据树未发现私密认证文件或eeprom.bin。独立ArduPilot checkout无修改，插件原有4项未跟踪资源保留。

## 10. Git 提交与交付状态

| 提交 | 内容 |
|---|---|
| `f146dad3eef2bb74f5786a473552765e39520b6c` | 统一合同/生命周期/资源 |
| `2faceb3c316b661f8fa69b8f50b179fad433fc5d` | 三车型标准库、外部接口、Action Lab |
| `71e52c551103241ca2b5a4c762dc45d840c1efcc` | 独立逐Action真值、严格SEND |
| `f4962ebf1db78080f9af6ae15a604140e3bfbe01` | 结果Schema、Session溯源、Query隔离 |
| `5651edf09b2b36dd9f3b2225a670984f89e18377` | 完整状态有界等待、FLU速度、外部异常、浏览器刷新 |
| `047bebafaf7bdb6f1d44407606200810da4d80e0` | 仅测试：Plane回绕与真实命令超时独立调度 |

正式运行始于干净工作区，验收期间没有源码变动。最终报告、索引与 README 作为单独文档提交；该文档提交的准确 SHA 见交付消息和 Git 日志，避免在自身内容中编造自引用 SHA。提交后再次检查工作区干净。

未解决的阶段内强制测试失败：无。协议、部署和使用限制见第5节。开发侧交付状态为 **READY FOR RE-AUDIT**，等待用户安排独立审查；本轮到此停止，不进入 Phase 4。
