# 目标一验收报告：MID-360 纯仿真接入与 RViz2

日期：2026-11-07。**总体结论：PASS，目标一完成。**

本轮已实际运行本机 ArduPilot SITL / Gazebo、ROS 2、RViz2、rosbag2 和原控制台。两车型运动、真实场景点云、采集时刻 TF、图形显示、录制回放、重启恢复、多实例和故障清理均有新证据。全量 1054 项 unittest、原生入口 25 项、控制台入口 8 项及补充进程/完整端口审计通过。没有把前一会话的代码、静态检查或测试结果当成本轮原生验收。

当前仍为明确标注的 Gazebo 均匀快照近似模型，不能用此结论证明真实 Livox 扫描、FAST-LIO2、SLAM、定位融合或实机能力。逐项机器可读结果见 [JSON 报告](MID360_GOAL1_ACCEPTANCE.json)。

## 工作区与执行环境

保留了起点 `44933be459ecb63864bc0660f30e1a19b129af49` 上的 27 个未提交文件；逐文件核实它们与隔离提交 `e093ddd270d11ab9dc016ab3f686b18a67b682f0` 完全一致。先保存补丁、未跟踪文件及 SHA，再从原工作区创建 `codex/mid360-goal1-acceptance`。仅导入 bundle 的分支引用，没有重复应用内容、reset、自动合并或推送。

工作目录为 `/home/level6/vehicle-autonomy-framework`，用户 level6 / UID 1000，隔离 `.venv` 的 Python 3.12.3。本轮 TCP/UDP loopback、本地 Unix IPC、Git 写入、DISPLAY=:1 / Xauthority、真实 X11 窗口及 NVIDIA RTX 3050 Laptop GPU 均可用。使用既有 HostEnvironment 外部软件索引：Gazebo Harmonic 8.15.0、ROS 2 Jazzy、RViz2、rosbag2；没有配置物理雷达网络或打开真实飞控/串口/雷达。依赖重新安装成功：

```bash
.venv/bin/python -m pip install -e '.[mavlink]' -r requirements-vision.txt
```

ArduPilot：`b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`；ardupilot_gazebo：`3ec51428fd43deb7b71137192ba16394b450d78e`。

本轮证据目录（均相对仓库根目录）：

- `artifacts/mid360-goal1-20261107-resume/`：环境、原始修改备份、bundle 比较、安装、单元测试、截图审阅、交付记录。
- `artifacts/mid360-native-20261107-r12/`：最终原生验收、截图、ROS 独立观察、动作请求、真值/Writer 采样、真实 bags、SDF 与进程/端口审计。
- `artifacts/mid360-center-20261107-r2/`：原控制台浏览器、三次 systemd 后台、正常/异常关闭、重启回放及截图。

前一会话受限执行的 NOT TESTED / FAIL 记录仍保留在 `artifacts/mid360-goal1-20261107/`；本轮早期失败轮次也保留，未改写为通过。

## 本轮修复与主要实现

沿用已有共同 GPU LiDAR 配方、独占模型副本及 SHA、独立 ROS 工作进程、动态真值 TF、示意车体、轨迹、LocalTools 监管和原认证 UI；没有重新实现另一套系统。

实际运行发现并修复：

1. ROS/Qt 工具缺少日志与缓存环境：为所属工作进程提供真实用户环境和私有 ROS 日志/缓存路径。
2. protobuf 点云缓冲区逐坐标重复复制，导致单帧约 1.4–1.9 秒：每帧只取一次原始缓冲区，转换降到几十毫秒；健康判定在处理结束后重新取当前时间，避免把处理前的时间当成新鲜数据。
3. 可选上游 CameraZoom 插件遇到新 LiDAR 的初始化错误：只在启用 MID-360 的独占相机模型副本中移除该可选插件，记录装配变化；不修改外部源模型、动力学或未启用 MID-360 的模型行为。
4. 录制完整性从 5 类加强为全部 8 类真实消息；录制开始即原子保存不完整索引，正常结束再保存真实数量和完整标志。
5. 控制台每次启动使用新目录，原实现遗漏旧运行中的录制：从 RuntimePaths 的既有自有控制台会话恢复完整录制，不接管旧 PID、DDS 域或车辆权限，不从历史 artifacts 加载软件。
6. 退役车辆重新打开的播放器不在当前车辆集合中，World 停止漏清理：在 World 的原关闭边界补清所属退役传感器工具。最终测试特意保持该播放器运行直至停止 World，没有降低清理断言。

验收脚本另修复了只读观察进程的完整 ROS 环境、与工作进程一致的本地发现配置、GUI 的独立非 ROS 库环境和自有窗口激活/截图。普通 Copter Goto 仍限高 2 米；脚本采用合法 1.8 米目标，没有放宽原 Action 限制。

| 主要文件（Python 路径相对 src/vehicle_autonomy） | 内容 |
| --- | --- |
| `simulation/sensors/mid360-approx-v1.sdf`、`configs/mid360-simulation.json` | 共同射线配方、两车型实际安装链和近似限制 |
| `app/simulation/mid360_assembly.py`、`camera_assembly.py` | 只装配实例副本、源与派生 SHA、可选相机插件处理 |
| `world/sensors/lidar/mid360_{data,worker,probe,replay}.py` | 有界转换、采集时间、ROS 消息、动态 TF、状态与回放来源 |
| `app/simulation/mid360_tools.py` | 现有工具监管、Domain 租约、录制完整性和历史录制发现 |
| `app/simulation/{manager,universal_runtime,scenarios}.py` | 选项、World 生命周期、退役工具与 L01 |
| `app/control_center/{backend,service}.py` | 跨后台录制恢复、原 RViz 入口分派 |
| `app/web/mission_control.py`、`app/web/static/simulation-center.*`、`mid360-ui.js` | 原认证/CSRF 下的有限传感器和工具操作 |
| `configs/rviz/mid360-visualization.rviz` | 真实 PointCloud2、Z 着色、示意车体、TF 和轨迹 |
| `tests/test_mid360_simulation.py` | 18 项转换、装配、租约、录制、恢复与退役生命周期测试 |
| `tests/simulation/mid360*.py` | 原生运动、只读 ROS 观察、控制台及完整关闭后审计 |

没有修改冻结 contracts、Core、Action/Execution/SafetyPolicy、Lease/TTL/session/generation fence、协议/Transport 或唯一 MAVLink Writer。所有运动由原 Action → Execution/Safety → Vehicle → 自有 ArduPilot SITL 执行。UNCONFIRMED 语义保留，清理进程不被当成物理停车证明。没有新增 Web 点云地图。

## 实际验收矩阵

下表证据中的 N 指 `artifacts/mid360-native-20261107-r12/`，C 指 `artifacts/mid360-center-20261107-r2/`，R 指 `artifacts/mid360-goal1-20261107-resume/`。

| 要求 | 状态 | 实际验证及证据 |
| --- | --- | --- |
| Rover + MID-360 持续真实点云、IMU、RViz2 | PASS | N/result.json、rover-live-observed.json、rover-rviz*.png；真实 L01 几何 |
| Copter + MID-360、起飞/移动/降落 | PASS | N/result.json 的 copter_flight、native/requests.jsonl、native/truth-writer.jsonl、copter-rviz-after-motion.png |
| 运动期间点云和动态 TF 更新 | PASS | Rover 位移约 0.863 m；Copter 最大三维位移约 2.060 m；两观察器 invalid 为空 |
| 外参、ENU/FLU、frame、采集时间、clock、采集时刻完整 TF | PASS | 两 live-observed.json；原 header stamp、全部逐点 offset=0、完整动态变换，拒绝静态 world 边；每域一个 clock/点云发布者 |
| 点云来自场景几何 | PASS | 世界坐标下墙面 x=11.85 m 命中超过 1700 点，建筑高度约 10 m、地面约 0 m；独立 ROS 观察与真实 Gazebo 画面对应 |
| 实际 Gazebo/RViz 画面、着色、模型、TF、轨迹 | PASS | 已实际打开并查看截图，N/gazebo.png、两车型 after-motion 和 replay 图片，R/visual-review.json |
| 两车型真实 rosbag2 正常结束、8 类消息 | PASS | N/native/application/simulation/sim-*/vehicle-*/mid360/recordings.json 及 bags；数量见下表 |
| 回放重新显示点云，实时/回放隔离 | PASS | N/*-replay-probe.json、*-replay-observed.json、*-replay.png；独立 Domain、唯一 clock、source=rosbag2，原状态改到 recorded_status |
| 仿真停止后录制回放 | PASS | N/result.json 的 retired_recording_replay；C/stopped-world-replay-probe.json、stopped-world-replay.png |
| 后台重启和异常退出后恢复录制 | PASS | C 三次后台；restarted-backend-replay*、crash-recovered-replay*、recording-recovery-audit.json；未完成录制未提升为完整 |
| 原控制台选择两车型、启用传感器、启动并打开两个原生 GUI | PASS | C/result.json、center-gazebo.png、两车型 center-live/reopened 与 web-panel 图片；浏览器错误为空 |
| RViz 独立关闭/重开 | PASS | N 两车型 rviz_reopen，C 两车型 UI reopen；新 PID、实时源持续在线 |
| 两实例同时运行，topic/TF/Domain/端口隔离 | PASS | N/result.json 的 multi_instance_isolation；live Domain 120/121、独立实体名/namespace/frame 和独立端口租约 |
| 单独停止 Rover，Copter 保持正常 | PASS | N/result.json 的 single_instance_stop；Copter 在另一车移除后序号仍增加 |
| 停止 World/后台清理所属源、播放器、录制器、GUI | PASS | N/result.json 的 simulation_cleanup（含退役车辆活动回放）、C 正常与 SIGKILL 后 cgroup 审计 |
| 僵尸、孤立进程/节点、完整端口释放 | PASS | N/post-cleanup-audit.json：29 个已记录进程的 PID/start_ticks 均不再匹配，全部工具退出已确认，无所属残留；10 个独立 TCP、辅助 TCP、FDM/UDP 端口实际绑定复查通过；C 三轮 cgroup 均空 |
| 中断雷达数据，旧数据不得继续在线 | PASS | N 两车型 fault_recovery；序号冻结、online=false，观察到空点云/空轨迹清除，再恢复新数据 |
| 终止 ROS 工作进程、依赖清理及重启 | PASS | N/result.json 的 worker_exit_cleanup：只终止自有源 PID，停止对应录制/实时 RViz，重启后取得新数据 |
| 异常关闭整个后台 | PASS | C/abnormal_backend_cgroup_cleanup，真实 systemd 主进程 SIGKILL，os-cleanup.json 无所属残留，下一后台可回放旧完整录制 |
| 相机与未启用 MID-360 的仿真回归 | PASS | N/camera_regression：实际在线源及 JPEG；disabled_mid360_regression：R01 普通 Rover + 相机启动、清理通过 |
| RS16 回归 | PASS | 真实 Gazebo bag 输入原 RS16 转换器显式 replay 模式，实际收到 720 栅格 LaserScan（含有效距离），control_eligible=false；并非物理 RS16 驱动测试 |
| 全量 unittest | PASS | R/unittest-final.log：1054 项，172.893 秒，无 failure/error |
| MID-360/Manager/场景/Web 定向回归 | PASS | R/targeted-final.log：50 项通过 |
| 两车型派生模型及 L01/R01 SDF | PASS | N/sdf-checks.json：本轮 5 个实际生成文件 gz sdf -k 通过 |
| 实机、真实 MID-360 非重复扫描、FAST-LIO2 | NOT TESTED | 按范围禁止实机；后两项不是本近似模型的能力，未实现或验证 |

没有未执行却标为 PASS 的条目。早期 r11 的 simulation_cleanup 为 FAIL；修复后的 r12 才通过，旧结果没有改写。

## 实际数据与图形检查

最终原生观察中，Rover 在初次数据检查时已有 310 个可在采集时刻完成 TF 的点云切片，Copter 有 655 个；两个静态安装边与真实动态 world→model 链分开。静止加速度模长均约 9.81 m/s²，角速度单位 rad/s，未声称绝对航向。最终持续观察分别验证 1106、1417 个 TF 切片。Copter 真值高度从地面约 0.195 m，上升到约 2.190 m，移动到约 x=0.983 m / z=1.790 m，降落回约 0.195 m。

第一份正常完整录制的 sqlite 实际消息数量（完整 namespace 和绝对 bag 路径在 JSON 报告及 recordings.json）：

| 车型 | points | IMU | 动态 TF | 静态 TF | clock | description | trajectory | status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Rover | 241 | 4839 | 2614 | 46 | 7055 | 46 | 232 | 174 |
| Copter | 368 | 7465 | 3064 | 53 | 7033 | 53 | 355 | 191 |

已实际查看最终 Gazebo、Rover/Copter 运动后及回放截图，也查看原控制台、新后台恢复和崩溃后恢复的真实截图。可见场景墙柱/车辆、按 Z 着色的几何点云、蓝色示意车体、TF 标记、黄色飞行轨迹，RViz Global Status 为 Ok，LIVE/REPLAY 标题明确。只截取所属窗口或当前测试网页，没有用空白窗口、进程存在、help 输出或合成图代替画面。

## 运行与复测流程

详细坐标、话题、QoS、字段、外参及限制见 [操作说明](MID360_SIMULATION_GOAL1.md)。普通使用流程：

1. 在隔离环境启动 `./control-center`，登录后进入“仿真中心”，选择 L01。
2. 配置 Rover / Copter，勾选 MID-360 近似模型；两车同时运行时选不同出生点。
3. 创建并启动会话，打开 Gazebo；选当前车辆，待实时在线后打开 MID-360 RViz2。
4. 在原车辆控制页按原流程取得控制权、双 SEND 和 SafetyPolicy，再执行 Rover 低速移动或 Copter Takeoff/Goto/Land。普通 Goto 高度仍不得超过 2 米。
5. 开始录制，结束并保存后选择 bag；选择回放来源，循环回放并重新打开 RViz。停止仿真后、正常重启或崩溃后新后台均可从旧会话选择完整录制。
6. 独立关闭 RViz、停止回放或停止 World；最后关闭后台，所属工具按原监管和 systemd 边界清理。未知 Domain 租约保持隔离，不自动清锁或接管进程。

本轮实际命令（验收目录均首次新建，补充审计只读已有真实结果）：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest tests.test_mid360_simulation tests.test_universal_simulation_manager tests.test_rover_scenarios tests.test_universal_simulation_web -v
.venv/bin/python -m tests.simulation.mid360 --run-dir artifacts/mid360-native-20261107-r12 --allow-send --gui
.venv/bin/python -m tests.simulation.mid360_center_native --run-dir artifacts/mid360-center-20261107-r2
.venv/bin/python -m tests.simulation.mid360_cleanup --run-dir artifacts/mid360-native-20261107-r12
```

复测应为两个原生启动命令更换新的目录；控制台测试若发现已有操作者后台，会拒绝接管。

## 物理限制与未解决事项

目标一范围内没有未解决的验收失败。保留以下明确边界：

- 水平 360°、垂直 −7°～52°、720×28 均匀光线、10 Hz 仿真时间快照；实际有效返回取决于场景，主机墙钟频率还取决于实时因子。
- 所有逐点时间偏移为零，不是 Livox 非重复扫描，没有模拟真实扫描先后、运动畸变或验证去畸变。
- 固定 0.1–40 m、2 cm 高斯距离噪声，不模拟反射率相关量程、天气、干扰、多回波。强度来自 Gazebo，不代表已标定真实反射率。
- Gazebo 理想 IMU 使用 SI 单位，未建真实 MID-360 内部 IMU 杆臂/器件噪声；外壳是 visual，不改变负载动力学。
- 真值 TF 和示意车辆模型只用于显示；没有进入定位融合、SLAM、Nav2、三维规划、避障或车辆控制。
- 崩溃未正常结束的录制仍为不完整，不自动修复或提升；未知域租约保持隔离。完整录制恢复不恢复旧车辆运行和授权。
- 实机与 FAST-LIO2 均 NOT TESTED；本任务没有连接或部署任何真实设备。

## Git 交付

正式分支为 `codex/mid360-goal1-acceptance`，提交基于原工作区起点，包含保留的原实现、本轮修复、可复现验收入口和本报告。没有自动合并或推送。

最终完整 commit SHA、父提交、文件清单及证据 SHA256 清单记录在 `artifacts/mid360-goal1-20261107-resume/delivery.json`。该文件在正式提交后生成，以避免提交内报告自引用自身 SHA；同目录 `MID360_GOAL1_ACCEPTANCE.final.md` 是附有完整最终 SHA 的交付报告副本。
