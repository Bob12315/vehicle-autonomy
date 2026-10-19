# P21–P25：Rover 基础自主导航完成审计

核对日期：2026-10-19。**P21–P25 在下述限定仿真范围全部完成。最终装配的 13 项物理门槛 PASS；260 项单元测试通过。**

范围是当前电脑的 ROS 2 Jazzy / SLAM Toolbox / Nav2 / ArduRover SITL / Gazebo。阶段编号沿用 [总计划](../autonomy_roadmap.md)，不重编号历史迁移、基础车辆 Phase 0–8 或暂缓的 P16。此次不是整个 Framework V1 的 100%，也不代替 P26 统一版本/长期运行验收。

## 阶段状态

| 阶段 | 当前结论 | 已有结果 / 边界 |
| --- | --- | --- |
| P21 命名目标导航 | PASS | Application 组织不可变目标、后台原生规划、最新地图准入和原执行链；历史规划取消/不可达证据保留，后续集成补强纳入当前单元 gate。见 [P21](phase-21.md)。 |
| P22 停车后有限重规划 | PASS | 最终新障碍到达、原生无路、第二次原生进程取消通过；旧运行退出/Disarm 后新建规划及租约。见 [P22](phase-22.md)。 |
| P23 地图与定位来源 | PASS | 轴对齐/旋转房间四壁与导出回读、map 锚点目标、定位来源/失效审查；活动控制仍为遥测，SLAM 候选只读。见 [P23](phase-23.md)。 |
| P24 自主业务整合 | PASS | 三检查点/一次有效观测、2.292 m 倒车返程，取消和对象消失均停止并 Disarm。见 [P24](phase-24.md)。 |
| P25 车型与配置复用 | PASS | 两种实际前驱几何、独立真值、配置/模型/参数 SHA；紧凑车正常/取消/地图丢失及原车默认平滑回归通过。见 [P25](phase-25.md)。 |

## 最终源代码与测试口径

运行逻辑与低速装配冻结于 `827582f`；相关源代码包括 `d66f12c`、`fddd426`、`a26c6bc`、`28c5e8e`、`8238ab8`、`4ff6790`。验收时源树指纹：

```text
d606bbb1a5d92afe9ebd0fe41f9df16110a27eca8de38294546a0afaaf6e1be4
```

不同阶段 manifest 的 Git HEAD、dirty 标志按实际启动保留。例如正常巡检在实现提交前启动、工作树非空，但源树指纹与提交后的最终矩阵一致。不能把所有历史开发场景说成同一个干净提交的构建。源树指纹包含运行包、仿真配置、参数、原生补丁、脚本和物理场景代码；便携摘要另记原始文件 SHA。

门槛完成后，整合复现脚本改为短序号目录，避免默认长用例路径超出 AF_UNIX 的 108 字节限制；已做 shell 语法及同等目录深度的真实 socket 绑定检查。此项只改变复现入口的输出路径，车辆/场景模块不变；不冒称修改后的整合脚本已经完整跑过一遍，也不将当前文档/入口整理的全树哈希与上述验收树混称。

**260 项根目录单元测试通过，0 失败、0 错误、0 跳过**：`python -m unittest discover -s tests -q`。原始日志 `artifacts/simulation/p25-final-unit.log`。历史 P20 的 223、P21 的 230 以及开发中的测试数均是各自版本，不相互替换。

最终 [单元证据](evidence/navigation-final-unit.json) 和 [13 项场景汇总](evidence/navigation-final-summary.json) 已提交。各阶段证据包含结果、实际所属进程、原生 worker、实际加载参数、收到的速度目标范围以及原始文件 SHA；大型日志留在本机 artifacts，可按命令重新生成。

## 最终物理矩阵

故障场景中的 FAILED/CANCELLED 是预期任务结果，不等于验收失败。以下 13 个声明的场景全部执行、全部 PASS，无跳过；不把开发失败或未执行的 P26/历史整车全套算进这个计数。P21 的纯规划取消/未知目标拒绝另保留历史证据。

| 场景 | 原始目录（`artifacts/simulation/`） | 关键结果 |
| --- | --- | --- |
| 原车默认平滑 | `goal-tracking-d6928a16` | SUCCEEDED，最大真值偏差 0.141 m、目标误差 0.078 m。 |
| 紧凑车导航 | `goal-tracking-81940606` | SUCCEEDED，36.125 s，偏差 0.100 m、目标误差 0.164 m。 |
| 紧凑车取消 | `goal-cancel-692ae29b` | CANCELLED，2.801 s 确认停车，Disarm。 |
| 紧凑车地图丢失 | `goal-map_loss-17079faa` | FAILED，2.500 s 确认停车，Disarm。 |
| 原车实体新障碍/重规划 | `goal-replan-e7cd2f9e` | SUCCEEDED，47.214 s；2 次准入，6.124 s 确认旧运动停止。 |
| 实体完全封路 | `goal-blocked-80298e1a` | FAILED，第 2 次原生 Nav2 无路 208，5.920 s 停车。 |
| 第 2 次原生规划中取消 | `goal-replan_cancel-825f30fc` | CANCELLED，实际 worker 被取消并释放，5.924 s 停车。 |
| 三点对象巡检 | `goal-business_inspect-d854038a` | SUCCEEDED，78.153 s，3 检查点/1 观测，实际倒车 2.292 m。 |
| 业务取消 | `goal-business_cancel-92521ce2` | CANCELLED，2.603 s 停车，Disarm，无后续检查点。 |
| 业务目标消失 | `goal-business_loss-57d9d41d` | FAILED，3.001 s 停车，Disarm，无后续检查点。 |
| 轴对齐地图质量 | `map-reliability-0.0-a82cb4be` | 四壁、导出回读、原生修复/ABI、只读定位候选 PASS。 |
| 旋转地图质量 | `map-reliability-0.15-10e8b183` | 同样四壁、回读、修复和只读检查 PASS。 |
| 轴对齐 map 目标 | `goal-map_goal-d593a063` | SUCCEEDED，33.626 s，偏差 0.072 m、目标误差 0.160 m。 |

13 个 manifest 的源树指纹一致；端口释放、remaining_process_groups=[]、所有所属进程停止、所有原生 job 进程组释放均已逐项核对。受测运动期间的状态/独立真值比对见 [定位记录](evidence/localization-status-crosscheck.json)，不声称独立 SLAM 精度。

SITL 复用 `suite-e8ba09fa/build/ardupilot/sitl/bin`，不宣称本轮重新空目录构建。ArduPilot 源版本 `b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`，Gazebo plugin `3ec51428fd43deb7b71137192ba16394b450d78e`，Gazebo 8.15.0。原生规划实际版本 Nav2 1.3.13；SLAM Toolbox 2.8.5 原生覆盖库检查 SDK/运行库及自身 SHA，最终库 SHA 为 `9edfc6ee2b7b8e4ed19fede848da5d7fc081c08a457140f97178cf38af3247f8`。

## 支持的装配

| 组合 | 实际车辆/定位/地图/行为 |
| --- | --- |
| 原前驱默认平滑基线 | 原 `target_rover/model.sdf`、原参数、前轴 +0.25 m；未被低速导航 SDF 替换。 |
| 原前驱扩展导航 | `target_rover/navigation.sdf`、显式导航参数；实际激光地图、有限停车后重规划、注册地图目标。 |
| 原前驱巡检 | 同一低速装配，遥测里程计对齐地图、Gazebo 对象 Observation；显式限速倒车，不要求原地 180° 掉头。 |
| 紧凑前驱 | 独立 SDF，轴 +0.18 m、轮距 0.58 m、轴距 0.47 m、5 kg 车身；相同协议/Core、不同几何与显式标定。 |

低速轮速执行器 P=4、I=0，仍用关节力闭环，力矩上限 8 不变。SITL 前馈来自实际轮距/轮半径/速度映射，黑盒 PARM 核对实际加载值。仅此受测仿真组合有效。后驱原型正常导航越界，未登记为支持；不因它的取消/地图丢失停车通过就称其已完成车型验收。

活动定位始终是 `vehicle_reported_odom`。SLAM 候选缺少独立高频 twist 等控制验收，始终 `control_eligible=false`，不做自动切换/融合。关闭 scan matching 的场景明确标为遥测对齐地图；不能把与遥测相关的 TF 一致性误报成独立 SLAM 定位精度。

## 保留的控制和资源边界

- Root 默认未连接生产车辆；双 SEND 默认 false。公开入口只接受注册任务，无任意 Twist/MAVLink 发送接口。
- 规划进程只持有不可变地图/目标；Mission/Action/业务不持有车辆端口。原 Execution、Lease、Safety、唯一 writer 保持。
- 跟踪命令上限 0.18 m/s、0.25 rad/s；Guidance 本身至多 0.15/0.20，显式倒车至多 0.10 m/s，默认不允许。
- 运行时横向 guard 0.15 m；独立物理验收保留原 0.30 m 路径门槛与车体间隙门槛。各场景另记实际观测值。
- 当前地图 ≤2.5 s，控制定位/状态 ≤0.5 s；原捕获时间不刷新。未知格阻挡，整段路径与写前短扫掠均校验。
- 单次跟踪 ≤70 s，Stop 退出屏障 ≤8 s、稳定 2 s。原生后台规划有有限超时/取消与进程组清理，晚到结果不能续跑。
- 只有显式预算下的当前地图路径阻断可以重规划；失联、时间/Frame/定位/源变化、Safety 和取消不通过重试绕过。
- 场景各有新 world/私有分区及独立端口；只清理记录过的所属 PID/PGID。停止未知仍是 `UNCONFIRMED`。

## 失败与修正

原始失败保留在 `artifacts/simulation/goal-*`，不改写报告：重复嵌套状态导致 IPC 探针迟滞；时钟/TF 到达顺序；射线稀疏未知格；动态物体造成扫描匹配对齐跳变；低速轮速积分/标定停滞；栅格端点偏移；180° 掉头偏离；后驱模型越界；重复 armed-only recovery。对应处理分别是精简状态、等待配套数据但保留时间、明确场景/拒绝条件、独立低速装配、碰撞校验的请求端点连接、显式限速倒车、限制支持车型和修正测试流程。没有提高数值保护或补画地图。

Native 端点连接保留原路径点，并再次独立校验；不是修改地图。SDF 执行器标定仍在真实刚体/碰撞仿真中运行；Gazebo truth 只用于被动测量及标准仿真对象输入，不供 Guidance/规划器驱动车辆。

## 复现和未完成项

配置见 [自主导航说明](../rover_autonomy.md)。顺序复现脚本：

```bash
export VAF_SIMULATION_SITL_BIN_DIR="$PWD/artifacts/simulation/suite-e8ba09fa/build/ardupilot/sitl/bin"
./scripts/test_autonomy_navigation.sh --allow-send
```

脚本创建新目录、新世界并逐项清理，不控制现有物理设备。正式 P26 统一版本、重复任务/长运行、资源配额及长期恢复尚未完成。P16 真实硬件继续暂缓；真实制动/失联、现场传感器标定、主动 SLAM/VIO 融合、三维/其他运动学、其他机型导航、Web/服务器与 AI Planner 均未由本轮获得支持。

本轮按阶段完成验收；上述脚本还包含 P21 的纯规划两个用例，提供完整顺序复现入口。不把分阶段记录冒称为一次已执行的 P26 长运行或空目录重新构建。下一阶段为 P26，需单独冻结版本范围及运行时长。
