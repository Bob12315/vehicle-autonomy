# 目标二：MID-360 三维 SLAM 建图与定位验收报告

日期：2026-11-09。开发状态：**已按用户要求暂停，目标二尚未完成**。当前整体状态：**FAIL**。只有下表全部具有实际证据才能宣布完成。
独立分支 `codex/mid360-goal2-wildthumper`，接续官方六轮车提交
`bd0bd33789eef27b2805f767a09cb36e89a0e231`。最终 SHA 记录在
`artifacts/mid360-goal2-20261108/pause-delivery-20261109.json`；本次按用户要求推送独立分支，不合并主分支。

## 当前验收矩阵

| 项目 | 结果 | 原始证据 |
|---|---|---|
| 两车型各三轮运动建图、精度与资源 | PASS | `artifacts/mid360-goal2-20261108/accepted-repetitions.json` |
| WildThumper 绕柱与实际回环优化 | PASS | `artifacts/mid360-goal2-20261108/pgo-rover-r4/slam-result.json` |
| Copter 六自由度路线与实际回环优化 | PASS | `artifacts/mid360-goal2-20261108/pgo-copter-r1/slam-result.json` |
| Rover 新会话匹配、错误初值及损坏地图 | PASS | `artifacts/mid360-goal2-20261108/relocalization-rover-r2/relocalization-result.json` |
| Copter 新会话匹配、错误初值及损坏地图 | PASS | `artifacts/mid360-goal2-20261108/relocalization-copter-r1/relocalization-result.json` |
| 两车型保存地图的独立新窗口 | PASS | `artifacts/mid360-goal2-20261108/saved-map-r2/result.json` |
| 实际 GUI 截图人工检查 | NOT TESTED | `artifacts/mid360-goal2-20261108/gui-review.json` |
| 故障撤销、回放隔离、多实例、重置与清理 | PASS | `artifacts/mid360-goal2-20261108/faults-r1/fault-result.json` |
| 控制台两车型、回放及三次后台生命周期 | FAIL | `artifacts/mid360-goal2-20261108/center-r1/result.json` |
| 原 MID-360、RS16、相机及禁用雷达回归 | NOT TESTED | `artifacts/mid360-goal2-20261108/regression-r1/result.json` |
| 最终进程、节点、端口及来源审计 | NOT TESTED | `artifacts/mid360-goal2-20261108/final-audit.json` |
| wheel 及资源完整性 | NOT TESTED | `artifacts/mid360-goal2-20261108/wheel/audit.json` |
| 全量 unittest | NOT TESTED | `artifacts/mid360-goal2-20261108/unittest-final.log` |

旧前驱/脚轮 Rover 的三次通过和失败均保留在 `artifacts/mid360-goal2-20261107/`，
不能作为新 WildThumper 的验收。新一轮只使用真实 Gazebo 场景计算的点云。

## 六轮实测

阈值在首次运行前固定，未放宽：ATE 0.30 m、1 s RPE 0.20 m、姿态 5°、
返回漂移 0.35 m、地图几何 P95 0.20 m、至少 2000 点/3 类地标；
IMU 括取 20 ms、点/IMU 偏差 10 ms、输出延迟 1 s、LIO 流程 CPU 300%、
RSS 2048 MiB、丢扫描比例 10%。CPU/RSS 包括 FAST-LIO、Adapter、地图子进程；
可选 PGO 的进程资源另行记录，不隐去其开销。阈值文件 SHA256：
`409cc2ab291962e1a8ddd4337e0985a6cd99ce353c2e46609bd4c0d21448ab96`。

真值只供独立裁判，按原采集时刻配对；只对齐第一次有效位姿的规约，
不拟合整条轨迹。返回漂移扣除实际路线未完全闭合的位移。

| 运行 | ATE m | RPE m | 姿态 ° | 返回漂移 m | 几何 P95 m | 延迟 s | CPU % | RSS MiB | 结果 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| rover 1 | 0.0874 | 0.0070 | 0.173 | 0.0970 | 0.1512 | 0.367 | 238.8 | 356.6 | PASS |
| rover 2 | 0.0871 | 0.0069 | 0.162 | 0.0969 | 0.1516 | 0.200 | 197.0 | 351.4 | PASS |
| rover 3 | 0.0923 | 0.0065 | 0.107 | 0.1009 | 0.1521 | 0.108 | 193.9 | 354.7 | PASS |
| copter 1 | 0.0273 | 0.0132 | 0.129 | 0.0403 | 0.1187 | 0.315 | 253.6 | 440.8 | PASS |
| copter 2 | 0.0368 | 0.0239 | 0.108 | 0.0175 | 0.0995 | 0.119 | 203.9 | 451.7 | PASS |
| copter 3 | 0.0356 | 0.0210 | 0.082 | 0.0235 | 0.1041 | 0.536 | 237.0 | 441.1 | PASS |

## 实现、物理限制与操作

普通 Rover（WildThumper）和 Copter 共用固定 FAST-LIO2、只读定位 Adapter、
有界地图子进程和 PCD 目录。原 Action→Execution/Safety→Vehicle→SITL 控制链保持，
不修改冻结合同、Core、双 SEND、TTL、Lease、session/generation fence、唯一 Writer
或 UNCONFIRMED 语义。LIO 不替换飞控控制反馈，不向 AP EKF 注入位置。

五个真实 GPU 渲染切片组成一帧，保留实际采集时间；不是连续逐激光的真实 MID-360。
切片内运动、真实器件反射率/量程、雨雾、多回波、器件温漂和新增负载动力学未模拟。
仿真 IMU 200 Hz；400 是缓存深度。均匀快照后端不能用于去畸变资格。
协方差为空、质量 DEGRADED；速度注明由 LIO 位姿按仿真时间差分。

局部 LIO、累计地图、PGO 历史优化、PCD 加载显示和有粗略初值的真实 ICP 匹配分别判断。
ICP 不承诺无初值全局地点识别；匹配失败或过期撤销状态。只有唯一 Adapter 按
原匹配采集时间发布 saved_map→local_map→odom→base→lidar。匹配显示使用精确
同采集时刻的原配准点云，不给旧 TF 或扫描换新时间。

Rover 表面/内部体素 0.30/0.50 m，Copter 0.15/0.20 m；
`configs/mid360-map.json` 配置独立累计地图的分辨率、范围、容量和观察过滤。
地图上限与轨迹、IPC、PGO 关键帧预算均有界。资源耗尽明确报错，不静默截断冒充完整地图。

启动、保存、加载、回放、PGO 和匹配步骤见 [使用说明](MID360_SLAM_GOAL2.md)。
固定依赖、许可证、编译及补丁边界见 [依赖记录](MID360_SLAM_DEPENDENCIES.md)。
外部软件/大型资源由 HostEnvironment 索引；RuntimePaths 管理持久状态；artifacts 只存验收输出。

## 修改与验证记录

主要文件：`app/simulation/mid360_slam.py`、`lio_probe.py`、`fast_lio_process.py`；
`world/mapping/lio_worker.py`、`cloud_map_worker.py`、`cloud_maps.py`、
`relocalization_worker.py`、`saved_cloud_worker.py`；`world/localization/lio_input.py`；
逐切片传感器装配/数据桥、依赖构建与锁、现有控制台及 RViz 配置。

此前修复包括真实零返回渲染事件、原始输入时间审计、原子文件替换竞态、
地图进程隔离与有界队列、ROS 字节数组序列化、轨迹限频和正确的新旧 TF 显示边界。
控制台单次回放验收改为录足真实采集时长；短片结束不应被视为无限在线数据。
全部旧失败证据保留，脚本没有放宽数值断言或把未运行检查标为 PASS。

原始命令、指标、Action 结果、位姿、独立真值、资源、PCD、元数据和实际截图均在
各矩阵证据对应的目录。单元测试或进程存在不能替代运动/GUI/录制回放验收。

## 未解决项目

矩阵中 FAIL 项需修复重测，NOT TESTED 项须补齐实际证据；当前状态不意味着目标完成。

## 2026-11-09 暂停提交记录

本次是保存开发进度的独立提交，不是目标二完成提交。用户要求暂停开发并提交到
Git/GitHub；暂停后没有继续开发或启动新验收。原始失败输出均保留。

- Rover 绕柱回环最新运行 `pgo-rover-r4`：35 项 PASS，实际绕柱 2.02 圈，
  最大定位延迟 0.289 s，LIO 流程峰值 CPU 289.64%，全程在线。
- Copter 回环 `pgo-copter-r1`：35 项 PASS。优化确有实际修正，但同采集时刻
  对比的返回漂移约 0.02496 → 0.02648 m；不能宣称短路线漂移改善。
- 新会话定位：Rover `relocalization-rover-r2` 为 PASS，3.635 s，
  位置误差 0.10245 m、姿态误差 0.19362°；Copter `relocalization-copter-r1`
  为 PASS，2.328 s、0.08561 m、0.24071°。错误初值和损坏地图分别检查。
- `saved-map-r2` 两车型独立新窗口 PASS，真实可见窗口截图已检查；
  重定位视图检查了 `relocated_registered` 原采集时刻的完整 TF。
- `faults-r1` 48 项 PASS，包括双实例隔离、点云/IMU/时钟中断、进程崩溃、
  真正的录制回放与空 World 重置。定位撤销分别约 0.701、0.762、0.675 s。
- 控制台 `center-r1` **FAIL**：两车型实时显示、录制、RViz 重开与地图管理
  已实际执行；停止 World 后的回放 SLAM RViz 就绪等待超时。后续后台重启及
  异常退出恢复检查未执行，不能据此标为 PASS。

六轮重复实验表为本轮前期的已接受快照，其后修改了原始显示轨迹限频、
CPU 计量和 UI；最终版本的六轮复测尚未进行。旧 CPU 峰值失败保留，
新计量使用纳秒级 POSIX 进程 CPU 时钟并记录读取不确定性，门限仍为 300%。
原始传感器显示轨迹按仿真时间 5 Hz 采样、最多按主机时间 2 Hz 发布；
点云、IMU、TF 的原始采集时间和频率保持。

此前 Rover 重定位 GUI 启动时有一次短暂数据失效并关闭窗口，失败记录
`relocalization-rover-r1` 保留，后续 r2 通过；不能据此承诺负载竞争下始终在线。
窗口缓存截图的旧侧栏问题通过抓取实际可见的所属窗口区域修正，旧截图不覆盖。

当前阶段最终全量 unittest、原目标一原生回归、最终六轮复测、最终 wheel
重建和 DDS/端口全面审计均未完成。已有 wheel 曾通过 15 项资源打包检查，
但构建早于最新 UI 修改，不能作为当前最终包通过。

暂停时进程列表未发现本轮验收驱动、FAST-LIO、PGO、LIO/重定位工作进程
或控制台启动器；这次进程盘点不替代尚未执行的最终 DDS/端口审计。
