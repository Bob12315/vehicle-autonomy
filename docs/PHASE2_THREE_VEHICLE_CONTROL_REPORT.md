# Phase 2：三车型基础仿真控制报告

状态：**READY FOR RE-AUDIT**。开发侧统一回归通过；独立审查记录另附，不自行宣布最终验收通过。

## 范围与基线

本任务的 Phase 2 指三车型基础控制扩展，不是传感器/AI/Mission Graph 阶段。
仅运行项目自有 localhost SITL + Gazebo。起始提交
`148a224fae4a652b8f250be827d8e79a9e41bbf9`，起始工作区干净，原 386 项单元通过。
分支 `feat/phase2-three-vehicle-control`。

已提交阶段：`97cddfc` 能力矩阵；`917c792` Plane 原生接口与滑跑模型；
`0bf8a34` Rover 原生 RTL、取消回收及独立原配置回归；
`bf5f8ea` 修复更新目标矛盾仍可能错误完成；`967d20f` 修复 TAKEOFF 取消窗口与陈旧地面状态；
`936f25d` 补齐 wheel 的 9 项三车型仿真资源。
控制和仿真输入在正式回归期间冻结。旧 Phase 1 报告、结论与非敏感证据不改。

## 官方依据与源码

详见 [能力矩阵](phase2/CONTROL_CAPABILITY_MATRIX.md) 和
[基线记录](phase2/BASELINE.md)。实际读取并保存七份官方页面快照，位于
`artifacts/phase2-control/reference-snapshots/`，索引含 URL、获取时间、文件 SHA256：
Rover Guided、Copter Guided、Plane Guided、TAKEOFF、AUTOLAND、automatic landing、geofence。

本机源码 ArduPilot `b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`；核对了三车型
GCS 命令入口、模式枚举、Plane TAKEOFF/AUTOLAND、Rover RTL、Waypoint/Pivot 和
原生围栏实现。所有三车型二进制实际从项目自有源码副本构建，未修改外部 ArduPilot
源码、参数或构建输出。Gazebo 8.15.0 与插件 `3ec51428fd43deb7b71137192ba16394b450d78e`。
实际二进制与插件哈希均在各运行 manifest 记录。

## 实现

- 七模块布局保持；新增 Plane 协议/状态适配在 `vehicles/plane/`，固定翼 SafetyPolicy
  在 `engine/control/fixed_wing_safety.py`，装配仍在 `app/bootstrap/simulation_runtime.py`。
- 新增 ONE_SHOT 的 `FixedWingTargetEffect/Command`：GeoPoint 高度明确为 AMSL 米。
  经统一 Execution、Safety、Authority 和唯一 Writer 编码 COMMAND_INT DO_REPOSITION。
  证据必须依次为新签名 ACK、当前匹配的新签名目标回报、之后的新签名 GUIDED 心跳。
  更新的已认证目标矛盾或不可解释回报会清除旧目标证据，才确认目标配置；不冒充物理到达、
  半径配置或停车。未认证/重放/不匹配/NaN 回报不能完成，超时 UNKNOWN。
- Plane 使用 MANUAL（仅未解锁地面）、GUIDED、LOITER、RTL、TAKEOFF、AUTOLAND 原生模式。
  常规固定翼拒绝 Copter 速度/悬停/直接起飞着陆效果和零速停止；危险空中 Disarm 被拒绝。
  TAKEOFF/AUTOLAND 的 Mode COMPLETED 仅确认模式生效，实际运动另作测量。
- 固定翼自主飞行每周期检查状态新鲜度和自身包络。取消请求 LOITER，经原受控通路发出，
  撤销权限并报告物理停止 UNCONFIRMED；链路丢失后 shutdown 保留该不确定结果。
- 新增独立 Rover Phase 2 配置，显式支持 RTL=11。原 `rover.toml` 及全部旧安全/物理阈值不变。
  RTL 的入队及最终写入都要求新鲜定位和已解锁；取消通过 Execution 请求 HOLD，
  等待模式确认之后的新鲜零运动样本，才确认停车。失联后不能报告已停车。
- 发送仍受双 SEND、Lease、TTL、Session、Generation 和最后时刻 Guard 检查约束。
  没有增加第二个运动 Writer，根入口仍不连接车辆，hardware_controlled 仍拒绝。
- 正常签名与严格单调时间戳验证沿用第三轮合同，8 位 packet sequence 仅用于帧序，
  ACK 相关性仍明确是 `unproven_mav_cmd_only`。签名不提供命令 UUID，也不构成实机安全认证。

## 仿真与测量合同

模型从上游 Zephyr 和 ArduPilot 插件 SDF 派生，保留空气动力、执行器映射与许可证，
新增三个自由滚动实体轮和轮轴阻尼，在跑道上平放启动。不使用手抛、额外启动力、
姿态/位置 teleport、内置 SITL 飞行动力学或 Mock 替代 Gazebo。

Plane 物理合同：至少 10m 地面滑跑且低于 1m 高度时有超过 8m/s 的观测；爬升达到
50m 目标的 5m 范围；原生目标配置后另核查飞向目标/至少 90° 转弯、目标周围 120m、
高度误差 7m、地速 8–28m/s 连续 3s；AUTOLAND 实际进近、接地、地面滑跑、低于 1m/s
连续 3s，并处在跑道宽度 ±15m、目标点 80m 范围内，最终新签名状态为未解锁。
这些为新增固定翼合同，不替换旧 Rover/Copter 门槛；不宣称完整一圈轨道精度或所有 AP 模式。

Plane 自有参数通过公开 PARAM_REQUEST_READ 回读、验签核实十二项，含起飞/返航高度、
进近距离/高度、油门端点和独立原生围栏。源码确认 RTL_ALTITUDE 单位为米，因此使用 50，
不是 5000。原生圆形围栏 2km、最高 150m、越界动作 RTL 配置/回读成功；未把这等同于
完成全部围栏越界故障认证。

Rover 新夹具仅增加独立参数文件，回读 RTL/WP 速度 0.5m/s、WP_RADIUS=0.2m、
Pivot 触发角 45°、最大转率 30°/s。原误差 0.75m、停车 0.10m/s、连续稳定 2s 保持不变。
新原生 RTL 取消测试必须在到达前实际平移，再确认物理停车，重新授权后恢复返航。
原配置的完整 Rover 物理场景也单独运行，避免以新夹具替代旧回归。

## 已保留的开发失败与修复

| 记录 | 结论/问题 | 处理 |
| --- | --- | --- |
| plane-development-1 | FAIL/人工终止；RTL 参数误用单位，持续爬升 | 保留原轨迹和日志；不修改 AP 源码 |
| plane-development-2 | FAIL；独立真值超过 150m 包络 | RTL_ALTITUDE 改为源码规定的 50m，加入公开参数回读 |
| plane-development-3 | 开发通过；初次滑跑和 AUTOLAND | 修正报告中 Disarm 后使用旧局部变量的记录问题；用最新 WorldSnapshot 复核 |
| plane-development-4/5 | 开发通过；原生目标、重放、期限、取消、失联与着陆 | 后续正式回归使用已提交冻结版本 |
| acceptance-917c792 | 中断/FAIL | 在 Rover Probe 期间停止，用于补齐 Rover 原生 RTL；不计为正式通过 |
| acceptance-0bf8a34 | 中断/FAIL；Rover Probe 和旧物理通过后停止 | 为修复新发现的目标证据矛盾问题，不计入正式通过 |
| acceptance-bf5f8ea | 中断/FAIL；第一轮三车型全过，第二轮在 Copter Probe 中断 | 发现 TAKEOFF 取消窗口缺陷，保留全部原证据后修复、重跑两轮完整验收 |
| plane-exit-before | 3 个确定性对照中 2 FAIL：已写出的 TAKEOFF 被旧地面状态清除跟踪；陈旧未解锁地面亦可清除 | 只有新鲜 VALID 的地面证据才可结束；活动飞行还要求未解锁；修复后 46 项定向、409 项单元通过 |
| plane-cancel-window-development/2/3 | 新真实测试夹具开发失败 | 依次为关闭过早未观察到移动、误要求 WorldSnapshot 为空、记录会话字段位置错误；保留原 FAIL，不改变控制/运动阈值 |
| plane-cancel-window-development-4 | PASS | 真实 ACK 在代理观察但不交给应用；取消后仍移动 0.865m，命令 UNKNOWN、停止 UNCONFIRMED，0 额外恢复写入 |
| wheel-resources-before | 9 项新资源全部缺失 | 补充显式打包清单；独立 wheel 安装验证 9 项资源、190 个生产 Python 文件与源码相同，原生目标编码有效 |
| native-target-contradiction-before | 稳定复现：目标 A 回报后出现新 B，再有 GUIDED 心跳，错误完成 A | 保留原 JSON 和原测试 FAIL；清除旧 A 证据，38 项定向测试和 406 项全量测试通过 |
| rover-rtl-development | 开发通过，返航误差约 0.64m | 增加取消后复行验证 |
| rover-rtl-development-2 | FAIL，复行后误差约 1.06m | 不放宽 0.75m；核对原生终点线和转向行为 |
| rover-rtl-development-3 | FAIL，过敏的 Pivot 设置影响 Goto | 保留失败，调整独立夹具为 45°，重跑全部物理场景 |
| rover-rtl-development-4 | 开发通过；返航约 0.63m，移动取消后实停 | 保留原回归并纳入统一入口 |

所有失败仍原样保留，未跳过测试或改写原结论。开发态部分实现/输入处于未提交状态，
对应 manifest 的工作树标记和当时参数回读保留；不将其冒充最终冻结版本验收。

## 统一回归

入口：

```bash
.venv-migration/bin/python -m tests.simulation.phase2_harness --allow-send \
  --sitl-bin-dir artifacts/phase2-control/ardupilot-source/build/sitl/bin \
  --run-dir artifacts/phase2-control/acceptance-936f25d
```

入口必须显式授权 SEND 和指定三个 SITL 二进制。每轮 Rover 为 Probe、原配置物理场景、
新增原生 RTL 物理场景、完整故障集；Copter 为 Probe、完整物理场景、完整故障集；
Plane 分别运行 TAKEOFF 已被飞控处理、应用仍只持旧地面状态的取消窗口，以及包含
物理飞行和真实代理故障的完整场景。两轮使用独立运行目录、世界/会话、
端口选择和临时密钥。原 Rover/Copter A–F 逐组及十五类故障、七项修复回归必须全部满足。

409 项单元全部通过，0 失败、0 错误、0 跳过；两轮共 18 个真实场景全部通过，三车型各轮 A–F 全通过。

| 轮次 | Rover 原生 RTL HOME 误差 m | Copter RTL HOME 误差 m | Plane AUTOLAND HOME 误差 m | Plane 低高度高速滑跑样本 | Plane 最终 armed |
| --- | --- | --- | --- | --- | --- |
| 1 | 0.668275 | 0.001196 | 1.003219 | 20 | False |
| 2 | 0.699508 | 0.001590 | 0.826421 | 20 | False |

运行 UTC：`2026-10-24T03:42:51.278159+00:00` 至 `2026-10-24T04:27:19.748495+00:00`；代码提交 `936f25d55e163be2703a98bcff6cea44a606999f`。
源代码与仿真输入 SHA256：`45347149aa68fd0a752bd67cfb2c59034c62dd228539deed45c82e9c3c824e46`，结束时完全一致。
原始入口/退出状态见 `artifacts/phase2-control/acceptance-936f25d/{summary,stages,unit}.json`。
每个真实场景都有独立 manifest、运行日志、签名支持证明、运行事件和物理轨迹；有代理的
场景另含收发/丢弃/重放原始帧。摘要和文件哈希见 [证据索引](phase2/phase2-evidence.json)。
Plane 的 LOITER 10s、RTL 8s 为实际模式和续飞段检查，不冒充完整盘旋一圈或完整返航精度验收。

新增取消窗口每轮独立启动真实 Plane：TAKEOFF 已在代理收到飞控 ACK，但不交给应用；
应用仍持原地面样本。取消后的实际运动证明旧地面样本不能证明停止。两轮均要求命令 UNKNOWN、
飞行停止 UNCONFIRMED、TAKEOFF Writer 1 次、额外恢复 Writer 0 次，且旧 World 样本时间/会话不被刷新。

wheel 独立安装在忽略目录的独立虚拟环境中，从 `/tmp` 使用 `python -I` 验证：9 项新增资源全在、
190 个生产 Python 文件与源码逐字节一致、Plane/Rover profile 可加载、原生 COMMAND_INT 编码正确。
MAVLink 可选依赖安装为项目规定的 pymavlink 2.4.49 / pyserial 3.5；未连接任何硬件。


活动原生 TAKEOFF 即使最后状态仍在地面，也保持飞行不确定性。新鲜 VALID、低速地面
证据方可证明已在地面；活动原生飞行还要求新的未解锁状态。低空 LOITER 被安全策略拒绝时，
不发送零速、空中 Disarm 或其他替代指令。断链后的 WorldSnapshot 保留原会话、原采样时间
的最后已知样本；它不是新的物理停止证据，当前会话/授权已撤销，命令 UNKNOWN。

两轮物理轨迹图见 [Plane 独立真值轨迹](phase2/plane-flight-truth.png)；图源为各轮
`trajectory.jsonl`，原 PNG/SVG 与哈希保留在证据索引。

## 边界

本次没有开发 VTOL、全量 MAVLink 命令、通用 AP Mission 上传器、Plane Web/业务任务目录、
传感器/AI、SLAM/Nav2 或实机连接。Plane 原生模式依赖所验证的 ArduPilot 版本和自有参数；
未认证链路不能从裸 ACK/HB 获得同等完成证据。下行签名排序不是任意网络延迟下的绝对物理
执行证明；不使用 packet sequence 充当请求 UUID。

隔离为项目自有状态目录、进程身份、独立世界/partition、端口选择和测试凭据；不宣称网络
命名空间或主机防火墙隔离。公开 SETUP_SIGNING 只用于自有未解锁 SITL；验证的是实际下行
ACK/HB 的 MAC 与接收新鲜度，当前 SITL 通道 0 的本机受信输入仍可未签名，不构成端到端实机认证。
轮式 Plane 模型仍依赖已安装的上游 Gazebo 插件/Zephyr 网格，未把 AP/Gazebo 二进制打入 wheel。

临时签名密钥沿用 P2 销毁策略，结束后删除自有持久状态和私有配置，保留非敏感日志。
销毁后不能再用旧密钥离线重新计算旧帧的 MAC，保留的是当时在线/独立验签结果。
普通覆盖/截断不宣称对外部快照、备份或物理介质取证的绝对擦除。

历史保护复核：与起始提交逐字节比较的 9 份原报告/索引不变；去重后的 724 个已索引
非敏感证据逐一 SHA256 一致。详见 `artifacts/phase2-control/historical-evidence-check.json`。

## 资源、审查与交付

正式 18 场景均验证临时凭据销毁、私有配置/状态消失、自有进程组为空和端口释放。
最终复查、外部环境未修改及 Git 工作区记录见证据索引和 `artifacts/phase2-control/final-delivery.json`。

独立 Codex 审查：待运行后填入独立审查结论与材料链接。
