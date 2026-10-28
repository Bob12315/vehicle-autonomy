# RViz2 Visualization Integration V1

2026-10-29 更新：Vehicle Control 现采用一次 SEND ON，后续动作及人工点击「执行此目标」
不再逐条勾选或弹出授权框；RViz 点选本身仍不执行。见 [SEND 开关说明](WEB_SEND_SWITCH.md)。
下文旧的确认框描述属于此前验收记录，控制边界与已知 Rover 风险仍保留。

2026-10-28。本报告只描述当前实现和实际证据；前置审计见
[架构审计](RVIZ2_VISUALIZATION_AUDIT.md)，审计提交 `3fc0540`。

## 实现范围与阶段

| Phase | 实际结果 |
|---|---|
| 0 审计 | 已完成。Web 场地图此前已撤除；Mission Studio 的图是任务图，保持不变。不存在可直接复用的完整通用 MAVROS/AP_DDS 车辆可视化装配。 |
| 1 Bridge | 新增可选 ROS 进程，只读取现有 Driver/VehicleState 快照，输出标准 Odometry、TF、实际 Path、NavSatFix、MarkerArray 和状态。没有第二条 MAVLink 连接、车辆命令端口或导航准入。 |
| 2 Profiles | Rover 顶视图；Copter、Plane 三维视图。三者均实际启动原生 RViz，订阅了对应真实 SITL 的状态、TF 和轨迹。没有合格 URDF 时显示明确标注的示意箭头。 |
| 3 Tool Agent | 复用现有 Registry、Agent、Supervisor。匹配车型、ROS Domain、Namespace、数据源与桌面能力；实际探测节点、当前数据和 RViz 订阅，不能以 PID 存活冒充 Ready。原有日志、停止、重启继续可用。 |
| 4 Web | Vehicle Control、Dashboard 的 Open RViz2 入口使用共享登录会话和现有主题；复用已有 QGroundControl 快捷入口。没有嵌入窗口、地图或三维网页。 |
| 5 导航联动 | 外部标准话题可配置订阅；私有 Pending Goal 接口先预览，人工确认后仅 Rover 的 odom 地面位置可调用现有 Goto。map、Copter、Plane 候选只预览。没有新增 Nav2 Action 或 cmd_vel 通路。 |
| 6 Workspace | Rover Navigation、UAV Visualization、Simulation Visualization 模板；依赖、共享引用、数据退化和 Agent 恢复沿用现有管理器。Simulation 模板验证并观察已由 Framework 拥有的 Gazebo/SITL，不再启动第二条车辆链路。 |
| 7 验收 | 单元、真实浏览器、真实 ROS/DDS 合同和三车型 SITL 分别记录；原始失败保留。复杂 Rover 停止确认存在未关闭的问题，见下文，不能声称三车型控制稳定性全部验收通过。 |

## 数据、坐标与时间

Bridge 位于 `src/vehicle_autonomy/app/visualization/`。`state.py` 读取发布快照，
`projection.py` 执行纯数据校验，`worker.py` 才在启动后导入 ROS。
默认车辆数据以 `/rover` 为例：

| Topic | 标准类型 / 含义 |
|---|---|
| `/rover/viz/odometry` | `nav_msgs/Odometry`；现有飞控报告位姿，非 SLAM 定位 |
| `/rover/viz/tf` | `tf2_msgs/TFMessage`；`rover/viz/odom → rover/viz/base_link` |
| `/rover/viz/trajectory` | `nav_msgs/Path`；最多 600 个实际不同采样，无计划轨迹伪装 |
| `/rover/viz/gps/fix` | `sensor_msgs/NavSatFix`；有效时的经纬度与实际 GPS 采样时间 |
| `/rover/viz/markers` | `visualization_msgs/MarkerArray`；实时示意模型、速度方向、相对 U 与年龄 |
| `/rover/viz/status` | `std_msgs/String` JSON；数据质量、参考系、错误和候选提交状态 |
| `/rover/viz/pending_goal` | `geometry_msgs/PoseStamped`；只产生候选，不驱动车辆 |

既有 VehicleState 已规范化 ENU/FLU，Bridge 不再做第二次 NED/FRD 转换。
Odometry 的 twist 从现有世界速度通过完整四元数逆旋转到 body FLU，包含倾斜和三维分量。
Rover/Plane 使用既有 GPS_GLOBAL_ORIGIN 投影，导出实际原点；Copter 未提供地理原点时
明确为 null，绝不从当前位置编造原点。`origin.json` 在私有工具实例目录保存最近四个
参考记录；它不覆盖飞控原点，也不作为跨会话重定位依据。

默认是隔离的可视化 TF 岛，没有虚构 `map → odom`。原点/车辆 session/generation
改变清空历史。坐标跳变、时间回退会阻止发布；位置跳变须新的源 epoch 或显式重启重新准入。
重复数据不刷新 Odometry/TF 时间。3 秒有效期沿用既有 Vehicle Control 保守采样边界，
屏幕标明 actual age，不构成高精度导航定位授权。已知坏 EKF 禁止发布；缺失或过期的
健康 EKF 报告只显示 UNKNOWN，不冒充健康。GPS 投影车辆没有有效 GPS 时不发布位置。

样本时间来自源实际捕获边界，包含保守 HTTP 往返延迟，不使用每次刷新时的 now 伪装
新采样。GPS 使用自身采样时间。AP 的 GPS 高度是 AMSL，不能直接填写要求椭球高的
NavSatFix.altitude，因此该字段为 NaN；AMSL 元数据仍在源快照。Odometry 协方差未知时
使用大值，GPS covariance_type=UNKNOWN，不编造精度。

失效时删除实时 Marker、清空 Path、停止重发位姿。历史 Odometry 显示默认关闭，
避免 RViz 保留的最后一个 glyph 被误认成当前实时位置。独立稳定时钟检测 /clock 暂停、
回退及系统时钟跳变；`use_sim_time=true` 必须有匹配的 /clock，否则不能 Ready。
默认 false。拥有隔离 TF 时检测额外 TF/Odometry 发布者；外部 TF 模式则完全不发布 TF。

## 安全与认证

Web 继续使用已有 HttpOnly/SameSite Cookie 会话、CSRF 和权限检查，页面切换不重新
要求密钥。现有 WebSocket 认证没有变更。可视化使用第三种独立私有凭据，既不是 Web
管理密钥，也不是 Agent 长期凭据，只允许读取可视化快照和提交惰性候选。不能控制车辆、
确认目标或访问其他 API。HTTP 客户端拒绝重定向，不使用环境代理，远端必须 HTTPS 或
显式 loopback 隧道。凭据不出现在 ROS 消息、URL、进程参数、浏览器存储或日志中。

RViz 的 SetGoal 只发布专用候选话题；另外重映射 `/goal_pose` 作为防御。无 Nav2 action
client、cmd_vel publisher 或直接 Vehicle Port。候选必须当前定位有效、同源 epoch、有限
坐标和单位四元数，最多 64 条、5 Hz、30 秒到期。odom ENU 地面候选仅 Rover 可执行；
map 候选没有合格变换/地图会话，只能预览。选定朝向亦只预览，现有 Goto 只执行位置。
执行仍须 Web 操作员已有控制权、显式 SEND 确认和既有 Action/Safety/Lease/TTL/唯一
writer。任务占有和 UNCONFIRMED 停止语义没有放宽，打开或关闭 RViz 不产生车辆 Action。

## 本机启动和操作

先按 README 在隔离环境安装项目和已有 ROS/Gazebo/ArduPilot 依赖。此主机已有
`scripts/with_ros2.sh` 私有 Jazzy 环境；其他主机用 `--ros-wrapper` 指定自己的可信入口。

```bash
cd /home/level6/vehicle-autonomy-framework
./scripts/start_visualization_sim.sh --kind rover
# 完整多旋翼桌面仿真（包含 Gazebo GUI，允许后续人工确认控制）：
./scripts/start_visualization_sim.sh --kind copter --gazebo-gui --allow-send
# 或 --kind copter / --kind plane；默认 Web 端口分别 8780 / 8781 / 8782。
```

该命令启动一个独占仿真部署、Web 和自动连接的 Desktop Agent，准备匹配 Workspace，
默认只读。不自动打开 RViz、Arm、起飞或执行 Mission。终端打印 Web URL 和登录密钥
**文件路径**；本地读取该私有文件，在统一登录页输入一次。进入 Vehicle Control 点击
Open RViz2，等待 Bridge 和 RViz 实际 Ready；窗口出现在 Agent 所在桌面。
Tool Manager 可查看运行/连接状态、日志及停止/重启；Workspace 页可启动已准备模板。
有其他已注册车辆时可选择车辆，切换只回收未共享的可视化工作区；共享/手动拥有的工具
需要明确处理，不能误杀。此命令本身一次只创建所选车型，不会在浏览器选择时偷偷创建车辆。

只对希望手动测试的本机仿真显式增加 `--allow-send`。随后仍要在 Web 申请控制权，Arm
和其他危险动作分别确认。Rover 可用原生 **2D Goal Pose** 选择候选，再回到 Web 的
待确认目标卡片确认执行。未经确认不会运动。Copter/Plane 不使用 Rover 地面导航执行。
按 Ctrl+C 关闭这个命令所拥有的部署。`--run-dir` 可指定全新私有证据目录，
`--duration` 可进行有限诊断。已安装 wheel 可用 `vehicle-autonomy-visualization-sim`。

对于既有远端部署：后端 `vehicle-autonomy-console`/owned simulation 增加
`--visualization-token-file /absolute/private/file`，Agent 主机生成可信配置：

```json
{"schema":1,"url":"https://framework.example","token_file":"/absolute/private/visualization.private","use_sim_time":false}
```

token 文件须由当前用户拥有、非 symlink、权限 0600。使用既有 Registry CLI 的
`--visualization-config /absolute/source.json` 加入三个车型的 Bridge/RViz profiles；
只有实际匹配的 ROS 与桌面依赖通过才可启动。后端与 Desktop Agent 的配置需由部署者
安全分发，不把 Web/Agent 密钥复制到 ROS。原有 Agent allowlist、身份和重连机制继续使用。

## 外部传感器、SLAM、Nav2

当前三个默认 SITL 没有在线、经准入的雷达/SLAM/Nav2 数据源。本轮不宣称真实 RS16、
雷达外参、SLAM 定位质量或自主 Nav2 导航验证通过。旧有专项环境不等于这个车辆会话的
合格定位源。标准 RViz 显示接口已保留，使用已有驱动，不开发第二个驱动。

可信 source.json 的可选 `external` 对象必须明确给出：
`origin_id`（与当前源 epoch 严格相同）、`fixed_frame`、`odom_frame`、`base_frame`、
`tf_topic`、`tf_static_topic` 和 `topics`。后者可映射 `scan`、`points`、`map`、
`global_path`、`local_path`、`global_costmap`、`local_costmap`、`perception` 到现有绝对
话题。类型分别使用 LaserScan、PointCloud2、OccupancyGrid、Path、MarkerArray。
外部模式不发布 TF，不强改外部话题；须先由部署者核实共同 ENU 原点、时钟和标定，不能
仅凭 frame 名字相同就建立 map/odom 变换。源 epoch 改变必须重新核实并更新绑定。
没有外部配置时这些图层关闭，不显示假的扫描、地图、路径或目标。
工具 Ready 证明当前车辆位姿/TF/轨迹数据与原生 RViz 订阅可用，不代表所有可选外部层
或导航系统均已准入；外部层需核对 RViz 自身的 Topic/Transform 状态和源健康。

QGroundControl 仍负责 GPS 地图，需要在现有 Registry 配置真实可执行程序和单向遥测
relay 证明；不满足依赖时快捷入口真实禁用，启动 RViz 不会伪造 QGC 连接。

## 测试命令与实际结果

基线 `python -m unittest discover -s tests -v`：747 passed。最终结果见提交的
[精简证据索引](evidence/rviz2-v1.json)，原始记录在本机 `artifacts/rviz-v1/`，不提交
临时凭据、主机日志或无关桌面截图。原生窗口证据见
[实际 Rover RViz 窗口](evidence/rviz2-v1-rover.png)。

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m tests.web_ui.browser_acceptance --run-dir artifacts/rviz-v1/ui-final-20261028
.venv/bin/python -m tests.visualization.launch_smoke --run-dir <fresh-owned-directory>
ROS_DOMAIN_ID=181 ./scripts/with_ros2.sh .venv/bin/python -m tests.visualization.ros_contract \
  --run-dir artifacts/rviz-v1/ros-contract-final-20261028
.venv/bin/python -m tests.simulation.program_launch --kind rover --visualization \
  --tool-registry runtime/tool-agent-dev/registry-native-final.json --run-dir <fresh-owned-directory>
# 对 copter、plane 分别执行同一 native acceptance；需要本机可信原生 ROS Registry。
# --visualization-extended 增加 Rover 原生鼠标候选与工具生命周期；只作用于新建的本机 SITL。
# --visualization-lifecycle-only 单独验证工具/Wait Mission/真实遥测中断，不额外创建车辆 Action。
```

浏览器验收使用明确标注的状态 fixture，真实 Chromium/HTTP，测试三车型、只读/控制权、
确认、页面切换、刷新恢复、Logout、过期、断网、390–1680 px 和零 JS 错误/零车辆写入。
真实 ROS/DDS 合同也使用显式 fixture，证明标准消息、命名空间、三维旋转、去重、过期
清除、TF 冲突、/clock 暂停/回退和凭据撤销恢复；这两类不冒充真实 SITL。

最终全量测试 **773 passed / 113.570 s**，包含原有 747 项；真实浏览器和真实 ROS 合同
另行通过。wheel 已构建并检查包含三个 Profile、Bridge 和启动入口，隔离环境安装及
pip check 通过（系统 pybind11 元数据警告与本次代码无关）。

`rover-lifecycle-v4-20261028` 原生工具专项整体通过：实际暂停/恢复本次 Desktop Agent、
明确重关联而不重复登录、停止/手动启动/查看日志/重启 RViz、Simulation Workspace
实际 Ready、共享手动 Bridge 未被误杀、独立 Wait Mission 成功。最后仅暂停本次拥有的
已解除武装 SITL，实际验证遥测中断后无位姿重发、轨迹清空和实时 Marker 删除；finally
恢复该进程，退出清理无残留进程组和临时 Agent/可视化凭据。

`launcher-final-20261028` 新启动器专项通过：自动连接 Agent、启动前没有工具实例，
手动 Open RViz 后实际原生 GUI/DDS Ready；导出实际飞控地理原点，三个 SEND 开关均为
false，无车辆 Action，页面切换复用登录，部署关闭和临时凭据删除均验证通过。

`rover-goal-final-20261028` 最终候选与工具专项整体通过：原生 RViz 工具栏鼠标选点、
候选提交前无额外 Action、Web 确认框和 SEND 勾选、现有 Goto 物理完成、Disarm，随后
同样完成工具/Workspace/Wait Mission 和真实遥测中断检查。此专项只使用直行候选，
不代替下文失败的复杂转向/ReturnHome 完整回归。

真正 SITL + Desktop Agent + 原生 RViz 的记录：

| 车型 | 已完成的实际控制和显示验证 |
|---|---|
| Rover | `rover-sync-20261028` 整套通过：模式、Arm/Disarm、前后行驶、转向、停止、Goto、ReturnHome；位姿/方向/轨迹实际更新，唯一 TF。原生 RViz 鼠标候选经 Web 确认后 Goto、返航与解除武装亦已实际完成。 |
| Copter | `copter-v2-20261028` 整套通过：两次起飞、三维运动/转向、持续运动 watchdog、真实失焦、浏览器断网、Goto、Land、RTL 后落地/解除武装，实际三维位姿/轨迹。 |
| Plane | `plane-first-20261028` 整套通过：MANUAL 模式及 Arm/Disarm、50 m 起飞、GUIDED 实际转弯、LOITER、RTL 实际接近原点、AutoLand 落地/解除武装；没有将固定翼作为可悬停车辆。 |

## 未关闭的风险和未验证项目

Rover 的后续完整复杂转向回归 `rover-goal-lifecycle-20261028` 中，Goto 物理目标已到达，
但退出停止确认出现 `stop_exit_deadline_unconfirmed`；较早 `rover-v3-20261028` 也曾出现
类似问题。因此一个完整通过记录不能覆盖后续失败，现有 Rover 控制在这种序列下的稳定性
**仍有风险**。本轮只显式启用已有签名源时钟同步，并校验已有串口配置；没有放宽停止
速度、时限、Lease 或 UNCONFIRMED 栅栏，没有为拿到通过结果清除故障。

`rover-goal-v5-20261028` 的原生候选 Goto 已成功，但随后 ReturnHome 出现 Action 超时。
同样保留为未通过记录。工具专项和后续候选最小闭环不替代原有完整运动序列回归，不能
以可视化或候选成功掩盖这两类车辆控制风险。

没有实机危险控制、真实 RS16/其他雷达连接、合格 URDF、在线 SLAM/Nav2 导航执行或
多主机时钟/网络生产环境验收。map 目标与飞行器候选保持预览；Simulation Workspace
不从浏览器动态创建新的 Framework 车辆。现有独立 Nav2/SLAM 进程如有自己的运动输出，
必须由部署者继续遵守 Framework 导航准入，不能因 RViz 接上数据就认为获得车辆控制权。
