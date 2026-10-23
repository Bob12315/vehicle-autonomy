# Phase 2：三车型仿真控制合同

本任务名称“Phase 2”指三车型基础控制扩展，不启动架构基线中的传感器、AI 或通用
Mission Graph 开发。仅隔离 localhost SITL + Gazebo，不开放硬件控制。
基线：`148a224fae4a652b8f250be827d8e79a9e41bbf9`，386 项单元测试通过。
官方文档读取日期：2026-10-23；源码核对 ArduPilot
`b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`。下表为本次受控接口范围，
不宣称支持 ArduPilot 的全部模式、所有飞机或任意低层姿态控制。

| 项目 | Rover | Copter | Plane（常规固定翼，非 QuadPlane） |
| --- | --- | --- | --- |
| 身份 | MAV_TYPE_GROUND_ROVER=10 | MAV_TYPE_QUADROTOR=2 | MAV_TYPE_FIXED_WING=1 |
| 模式 | HOLD=4，GUIDED=15 | GUIDED=4，LOITER=5，RTL=6，LAND=9 | MANUAL=0（仅地面）、GUIDED=15，LOITER=12，RTL=11，TAKEOFF=13，AUTOLAND=26 |
| Arm/Disarm | 正常 CMD400，不强制解锁 | 同左；空中禁用危险 Disarm | 正常 CMD400；新鲜地面低速状态才允许 Disarm |
| 本地位置 | odom ENU → LOCAL_NED，平面目标 | odom ENU → LOCAL_NED 三维位置和 yaw | FixedWingTargetEffect：COMMAND_INT DO_REPOSITION，AMSL 航点；飞往后持续盘旋，非悬停流 |
| 速度/转向 | base_link FLU 前进/后退/偏航率 | ENU/FLU 三维速度和偏航率 | 不接受零速悬停或 Copter 的速度向量接口 |
| 起飞 | 明确不支持 | GUIDED + NAV_TAKEOFF，另核查物理高度 | 原生 TAKEOFF 模式，地面滑跑、旋转、爬升；目标由已核查的 TKOFF_* 仿真参数设置 |
| 着陆 | 明确不支持 | NAV_LAND/LAND，观测接地 | 原生 AUTOLAND，基于真实起飞航向建立进近；必须已经飞行且飞控已捕获航向 |
| 停止/取消 | 受控零速，后续状态确认停车 | 受控零速并观测悬停；着陆另行请求 | 受控 LOITER/RTL/安全着陆，继续保持飞行；不能报告“速度为零/已停车” |
| 失联 | 撤销权限、丢弃旧队列，停车未确认 | 同左，停止未确认 | 撤销权限、丢弃旧队列，飞控自身保护继续；不伪造盘旋或着陆已确认 |
| 成功证据 | ACK 与新签名 HB / 新采样运动状态 + Gazebo 真值 | 同左；起飞/着陆不以 ACK 代替运动 | 模式生效或 ACK+新 GUIDED HB+新签名目标回报确认目标配置；物理到达/滑跑/飞行/接地另由 Gazebo/遥测验证 |

统一要求：双 SEND 默认关闭、显式 SafetyPolicy、Lease/TTL/Session/Generation、唯一
MAVLink Writer、有效下行签名和防重放合同、未知结果 UNKNOWN、资源归属与凭据销毁。
原 Rover/Copter 阈值不扩大。Plane 使用独立适配其空速、转弯半径和飞行范围的安全配置，
不能把扩大 Copter 阈值作为固定翼实现。

## 官方资料与源码核对

- [Rover Guided commands](https://ardupilot.org/dev/docs/mavlink-rover-commands.html)：
  `Rover/GCS_MAVLink_Rover.cpp` 的 SET_POSITION_TARGET_LOCAL_NED 分支；
  位置忽略 yaw，非完整横向/竖向速度控制。
- [Rover modes](https://ardupilot.org/rover/docs/rover-control-modes.html)：`Rover/mode.h`。
- [Copter Guided commands](https://ardupilot.org/dev/docs/copter-commands-in-guided-mode.html)：
  `ArduCopter/GCS_MAVLink_Copter.cpp`、`mode_guided.cpp`；速度目标需刷新。
- [Copter modes](https://ardupilot.org/copter/docs/flight-modes.html)：`ArduCopter/mode.h`。
- [Plane Guided commands](https://ardupilot.org/dev/docs/plane-commands-in-guided-mode.html)：
  `ArduPlane/GCS_MAVLink_Plane.cpp::handle_command_int_do_reposition`；必须使用
  COMMAND_INT/地理位置语义，不能复制 Copter 本地三维速度控制。
  文档正文的 x/y 经纬说明与其例子不一致，应以协议字段及本机源码为准：x=纬度，y=经度。
- [Plane TAKEOFF](https://ardupilot.org/plane/docs/takeoff-mode.html)、
  [automatic takeoff](https://ardupilot.org/plane/docs/automatic-takeoff.html)：
  `ArduPlane/mode_takeoff.cpp`、`takeoff.cpp`。当前源码直接 NAV_TAKEOFF 命令分支针对
  QuadPlane，常规 Plane 采用原生 TAKEOFF 模式或 AUTO 任务，不能照搬 Copter。
- [Plane AUTOLAND](https://ardupilot.org/plane/docs/mode_autoland.html)、
  [automatic landing](https://ardupilot.org/plane/docs/automatic-landing.html)：
  `ArduPlane/mode_autoland.cpp`、`libraries/AP_Landing/AP_Landing_Slope.cpp`。
  当前版本支持模式 26；进入条件包含正在飞行及已捕获起飞方向，进近和接地不能由模式 ACK 推定。

## 必须实际验证

Rover：前进、后退、转弯、本地 Goto、停车、取消、失联、授权/过期拒绝。
Copter：起飞、悬停、ENU/FLU 位移/速度、转向、LOITER/RTL、着陆、取消、失联和授权拒绝。
Plane：轮式地面静止 → 持续滑跑 → 离地爬升 → 原生巡航/转弯/盘旋/返航 →
AUTOLAND 进近 → 接地滑跑 → 低速停稳/Disarm；加上空中危险命令拒绝、失联、旧报文
重放、会话变化及凭据清理。三车型每项已通过/失败/未执行的状态以最终报告和原始证据为准。

当前矩阵是实现/验证合同；Plane 已完成开发态物理验证，正式统一回归及独立审查状态以最终报告为准。

Plane 独立容限：AMSL 目标映射到当前 odom 后，飞行目标高度 20–140m，目标半径
离 2km 原生圆形围栏至少 200m；当前状态最高 150m、地速不超过 35m/s。
自有 SITL 配置并回读原生围栏：FENCE_ENABLE=1、FENCE_TYPE=3、FENCE_ACTION=1（RTL）、
FENCE_RADIUS=2000、FENCE_ALT_MAX=150、FENCE_ALT_MAX_TP=1（相对 HOME）。
主机检查不能冒充飞控保护已经执行；越界/失联撤销权限后，物理飞行结果仍为 UNCONFIRMED。
返航高度参数在此源码版本的单位为米，RTL_ALTITUDE=50，启动通过公开参数回读核实。
[原生围栏说明](https://ardupilot.org/plane/docs/common-geofencing-landing-page.html)及
`ArduPlane/fence.cpp`、`libraries/AC_Fence/AC_Fence.h` 确认其语义。

固定翼取消先通过 Execution 请求 LOITER，再撤销权限并返回
`fixed-wing-flight: UNCONFIRMED`；这不意味着飞机已经物理停止。低空不满足安全切换条件、
ACK/状态不充分或链路失效时如实保留不确定结果，绝不发送零速度/强制空中 Disarm。
