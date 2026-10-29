# 固定车辆库与纯装配 Spawner

日期：2026-10-29。车辆定义位于 `simulation/vehicles/catalog.json`，装配代码属于
`app/simulation/vehicles.py` 和 `spawner.py`。它们不读取 World，也不创建飞控命令端口。
`READY` 只表示固定输入完整且 SHA 锁一致；实际 Gazebo、SITL、Framework、Web 与物理运动
须分别验收，不能由资源就绪推定。

## 固定定义

| id | 固定版本 / 模型 | 固定 profile | 原点贴地高度 / 平面包络 / 高度（米） |
|---|---|---|---|
| rover | 1.0.0 / target_rover | rover_phase2.toml | 0 / 0.72 / 0.5 |
| copter | 1.0.0 / iris_with_gimbal | copter.toml | 0.195 / 0.65 / 0.5 |
| plane | 1.0.0 / twin_cessna | plane.toml | 0.22 / 1.5 / 0.65 |
| vtol | blocked-1 / 无已准入定义 | 无专属 Framework VTOL profile | 未知 |

几何包络用于保守出生点筛查，不替代网格接触或实际跑道验收。原点高度来自既有已验证车型的
安装约定，不随地图改变质量、惯量、碰撞、动力学、传感器、外参或飞控参数。
默认读取隔离 `artifacts/phase2-control/ardupilot-source`，缺少时才选用户的
`~/ardupilot`。显式 `ardupilot_root/plugin_root/twin_root` 可配置部署位置；其内容仍须
满足同一源锁。二进制、插件或参数变更会阻塞，须另建版本、审计并验收后更新受信目录；
运行时没有自动重新锁定或从网络下载的路径。

`VehicleRegistry.get/list_vehicles` 返回可 JSON 序列化的定义，包括源路径、固定参数顺序、
全部递归模型资源 SHA、二进制与插件 SHA、版本和 fingerprint。`model_hash` 覆盖所用模型
目录的全部文件及递归 include；`parameters_hash` 按有效叠加顺序覆盖参数文件；
`sensor_hash` 覆盖真实传感器配置和完整模型/include/link/sensor 位姿链。
`physics` 展示每个 link 的原始 inertial、collision、joint 和动力学插件配置；
`actuators` 展示 AP 插件每个 channel 的完整 control map。位姿保留 `degrees`、
`relative_to` 与所属作用域，不把不同坐标系的数值简单相加冒充已求解外参。

## 独立实例装配

`prepare(kind, directory, entity_name=..., instance=..., system_id=...)` 只接受新的空目录。
模型及递归资源、参数和 profile 均复制到自有目录；源模型、外部 AP、Gazebo 插件和
Twin 项目保持只读。根模型只改变实体名称、loopback FDM 端点和必要的绝对 topic 命名空间。
复制件的 include 和 mesh URI 绑定到自有绝对资源路径，避免动态添加时复用外部可变网格，
并兼容独立 libsdformat 结构检查；这不会改变
惯量、关节、传感器参数或动力学内容。每个实例返回同一个源模型与传感器 fingerprint，
另记录实际装配 SDF 的 `prepared_model_hash`。

参数文件逐字节拷贝，system ID 由独立 SITL 启动参数绑定。TwinPayload 插件源码只读提供给
既有的自有目录构建流程；不复用未知 ABI 的外部载荷插件，也不提供新的载荷控制路径。
世界出生点、地形、跑道、相邻车辆间距和实体注入由上层 World/Runtime 校验，库没有地图分支。

`PortLease.acquire` 在 40..100 选择实例，持有 flock，并同时探测：TCP
`5760+10I`、`5762+10I`、`5763+10I`；UDP `9002+10I`、`5501+10I`。
system ID 为 `I+1`。端口被占用时跳过，不停止占用者。锁必须在自有 SITL 完全清理后释放。
探测 socket 在 SITL 启动前释放，因此 flock 是合作进程之间的所有权约定；实际启动仍须
检查绑定失败并保守退出。命令发送继续经过原 Action/Execution/Authority/Safety/唯一 Writer，
两个 SEND 默认关闭，Plane 取消仍保留 UNCONFIRMED。

## VTOL 官方来源审计

存在真实官方候选，不能宣称“官方没有 QuadPlane”。固定版本
[SITL_Models 25bc38e / Skywalker 文档](https://github.com/ArduPilot/SITL_Models/blob/25bc38ed8c6c0345840159a8cbc0b02781d52f3c/Gazebo/docs/SkywalkerX8.md)
提供 `skywalker_x8_quad`、AP JSON 插件及独立 QuadPlane 参数。已下载官方固定提交到忽略的
本地缓存，检查 8 项模型资源全部存在、AP channel 0/1/2/4/5/6/7 控制映射以及
`Q_ENABLE=1 / Q_FRAME_CLASS=1 / Q_FRAME_TYPE=3`；`gz sdf -k` 返回 0。
文档明确 Q 模式使用默认参数，不能把普通翼面飞行调参当成 VTOL 过渡已验收。

官方
[ardupilot_gz 8df4dc1 / Alti launch](https://github.com/ArduPilot/ardupilot_gz/blob/8df4dc1726e37504e6fc8b952d02e554cfa3176f/ardupilot_gz_bringup/launch/robots/alti_transition.launch.py)
也提供 `alti_transition_quad` 的 ROS 2 装配，引用 SITL_Models。该 ROS 2 外部启动器不是
Framework 的 VTOL Safety、Translator、Action 和所有权准入，也不会在普通库导入时运行。

当前 VTOL 仍为 **BLOCKED**：尚无专属 Framework 控制 profile、模式/过渡/取消安全语义，
未完成原生 SITL、起降与过渡验收；Skywalker 资产的许可追溯也未完成。
SITL_Models 所审模型目录及仓库根未发现可直接适用的资产许可，另一个
`scripts/VTOL_model/LICENSE` 不能替代 Gazebo 网格/纹理许可。模型的 credits 指向
PX4/SwiftGust 与 RealFlight 纹理来源，后续须逐项确认。未将该模型加入可启动列表，
未将 Twin Cessna 当作 VTOL，未改固定翼核心 Safety/Translator。

现用 ArduPilot 插件来自
[官方固定源 3ec5142](https://github.com/ArduPilot/ardupilot_gazebo/tree/3ec51428fd43deb7b71137192ba16394b450d78e)，
其许可文件为 LGPL-3.0；AP 源许可为 GPL-3.0。实际 `ldd` 检查显示现用插件链接
`gz-sim8 / gz-transport13 / gz-msgs10 / sdformat14`，无缺失库。Twin 项目模型的
可再分发许可没有凭空推定，本库只读取用户现有输入，不把外部模型打包进 Git/wheel。

机器来源、固定提交、SHA 与阻塞原因保存于 `simulation/vehicles/vtol-audit.json`；
原始 clone、API 403 失败、结构检查和依赖日志位于
`artifacts/simulation/vehicle-library-audit/`。首次 GitHub tree API 遇速率限制后改用
官方浅层 sparse clone，没有改用未知镜像。

## 本子模块验证

8 项隔离合同测试通过；三种真实固定输入分别装配到两个新目录，源
model/parameters/sensor/fingerprint 全部一致，参数副本逐字节相同；三个根模型的
`gz sdf -k` 均返回 0，全部 SDF URI 指向自有副本。证据为
`artifacts/simulation/vehicle-library-assembly-20261029-r3/result.json`。
首次 Copter 检查因 libsdformat 缺少 Gazebo URI callback 失败，保留在前一目录；
绑定自有 include 路径后才重测通过。本子模块没有启动 Gazebo/SITL，也不将这些检查
计为车辆物理运动或 World×Vehicle 跨地图验收。

固定车型跨地图运动、独立 owner 与 Web 多车的后续实际结果见 [通用验收报告](UNIVERSAL_SIMULATION_TEST_REPORT.md)。本页“本子模块未启动仿真”仅描述车辆库子模块自身的装配检查，不覆盖后续集成测试。
