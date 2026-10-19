# P20：Rover 路径消费与安全跟踪

本阶段把 P19 只读 Nav2 路径接入正式 Application / Mission。适用平台限定为本机 `target_rover`：前方两主动轮、后方两万向轮，ArduPilot Rover SITL + Gazebo + P18 SLAM Toolbox。它不是通用车型控制器，也不改变默认关闭 SEND 的行为。最终实测结果见 [阶段审计](autonomy/phase-20.md)。

## 运行链

```text
Gazebo 实际激光 → ROS 2 / SLAM Toolbox → MappingInput → WorldSnapshot.map
                                             ↓
App 公开 status + 独立 app.plan → Nav2 → executable=false 的几何路径文件
                                             ↓
显式 start follow_path → 路径准入 / 帧绑定 / 重新校验
                                             ↓
GUIDED → Arm → FollowPathAction → 观察到停车 → Disarm
                       ↓
                  Typed Twist / Stop Effect
                       ↓
原 Execution → 双 SEND → Lease → Safety → 最终地图检查 → 原唯一 writer
```

ROS 不运行 Controller Server、BT Navigator 或 `/cmd_vel` 到 MAVLink 的发送桥。耗时的 Nav2 计算在独立进程执行，不阻塞 10 Hz 车辆周期。Action 只读取 WorldSnapshot 和只读 NavigationReader，输出 Effect。

## 必须显式选择的几何语义

这个模型的主动轮轴位于 `base_link` 前方 **0.25 m**。原地转向时，车体原点会沿弧线移动。P20 跟踪的是**主动轮轴中心**，不是车体原点：

```text
x_ref = x_base + 0.25 cos(yaw)
y_ref = y_base + 0.25 sin(yaw)
```

Map、Localization 和原车辆遥测合同保持不变；该偏移只在路径准入、Guidance、最终地图检查和独立验收时显式使用。路径点仍是 `map` / 绑定后的 `odom` 坐标。

模型全部车体、轮子及万向轮转动范围，按主动轮轴包在 **0.72 m** 圆内。执行要求规划余量至少 **0.95 m**，在线最大横向偏离 **0.15 m**，发送前检查 **0.76 m** 圆的短期扫掠。P19 默认的 0.55 m 只读几何路径不能直接用于这个执行器。

配置声明 `target_rover_front_axle_v1` 是对这一模型的明确选择；其他轴距、车体、执行器或真实硬件需要重新适配和验收，不能照抄该偏移或余量。

## 手动运行

先启动自己的 localhost Rover SITL / Gazebo / P18 Mapping 栈。创建绝对路径配置，例如：

```toml
schema = 1
model = "target_rover_front_axle_v1"
plan_path = "/absolute/path/live-plan.json"
timeout_ns = 70000000000
```

配置只在启动时加载。超时允许 1–70 s，配置变更需要重启。启动 App 时，路径文件可以尚未生成：

```bash
python -m app.main run --profile rover_sim \
  --config /absolute/path/rover-profile.toml \
  --control-socket /absolute/path/app.sock \
  --ros2-mapping-config /absolute/path/mapping.toml \
  --navigation-config /absolute/path/navigation.toml --allow-send
```

App 空闲时双 SEND 仍关闭。等待 READY、原点检查通过、45 s 仿真预热结束、在线地图有效，然后查询：

```bash
python -m app.main ctl --profile rover_sim \
  --control-socket /absolute/path/app.sock status
```

使用 `navigation.planning_start.position` 作为规划起点。这个状态字段已显式把当前主动轮轴从 odom 投影到 map，包含 frame epoch 和原位姿采集时间；过期/缺失时为 null。目标同样是 **map 中主动轮轴要到达的位置**，不能把 odom 坐标直接当 map 坐标。

在另一个进程中运行 P19 只读规划，替换下例中的起终点为当前地图中的明确数值：

```bash
python -m app.plan --mapping-config /absolute/path/mapping.toml \
  --control-socket /absolute/path/app.sock --frame map \
  --start 0.25 0.0 --goal 0.8 2.0 --clearance 0.95 \
  --output /absolute/path/live-plan.json
```

这组坐标仅是验收场景示例；其他地图可能拒绝。成功响应仍标记 `executable=false`，只代表几何结果。文件本身不授予车辆权限。生成后须在原规划截止前显式启动：

```bash
python -m app.main ctl --profile rover_sim \
  --control-socket /absolute/path/app.sock start --mission follow_path
```

IPC 只接受已注册 Mission 名，不接受路径、原始 Twist、MAVLink 或 SEND 开关。

## 准入、时间和版本

- 路径文件须为有界普通文件，拒绝符号链接、FIFO、超大文件、非法结构/数值；长度限制为 0.1–20 m，2–8192 点。
- 仅接受 P19 的成功输出、受支持后端、`map`、`live_map`、当前应用 Frame epoch、同一地图资源/源 generation、有效源时间和未过期的规划截止。记录地图、跨时钟、旧 epoch、未来/过期计划均拒绝。
- 原始 SHA 内容从 MapStore 重新加载校验；对**当前**地图再次检查完整路径。相同 revision 不允许伪装成不同 SHA/采集时间。允许同一源的新地图版本，但不能仅凭旧地图仍安全就执行。
- 当前主动轮轴须距路径起点 ≤0.20 m，Localization / telemetry ≤0.5 s，当前地图 ≤2.5 s；地图和 WorldSnapshot 的资源引用必须一致。
- 把准入时实际观测的平面 `map←odom` 关系绑定到这个有限任务；不是假设两个 Frame 恒等，也不是向 TransformTree 填一条永久静态关系。路径只转换一次到 odom。
- 原规划截止用于**准入**。准入后由单独、有限的 Action 截止和持续的新鲜地图/状态检查约束执行；不会把文件时间戳刷新成新的车辆授权。
- 每个 request ID 在一个 App 进程中只能消费一次（最多 128 次准入）；任务结束不自动续期、重试、重规划或恢复旧运动。

## 执行中的失效

同一来源的新地图内容需要再次完整验证绑定路径，未知、模糊占据、障碍和地图边界都阻挡。每次验证记录新 SHA/revision。观测到的 map/odom 对齐变化会投影到整条绑定路径上，最大位移超过 **0.10 m** 即中止；界内也必须重新检查新地图里的整条路径，不能跳过几何校验。

每次实际运动写入前，原 writer 在原有授权/Lease/TTL/状态检查后调用只拒绝的附加地图 guard，重新检查状态年龄、地图年龄、路径文件 SHA、横向偏离、速度边界和一秒扫掠。地图输入在同一 App 周期的写入前轮询，因此上一周期排队的命令会受到新地图失效约束。外部变化最迟在下一次轮询采纳，不声称零延迟感知。

Guidance 有单调局部路径进度、有限前视和角速度反馈；大航向误差先转向，避免跨路径交叉处跳到远端。实际控制为低速 body X + yaw rate，不使用侧向/垂向速度。最终位置不包含朝向任务，也不是带时间的轨迹。

取消、超时、地图丢失、地图/源 epoch 改变、路径文件修改或超限偏离均进入原 StopMotion 退出屏障。停车允许在地图失效时继续发送；须有新车辆状态确认低速并稳定 2 s，原 8 s 截止不放宽。失败/取消后不会自动 Disarm 或续跑；确认状态后可显式启动已有 `safe_recovery`。

链路失联时仍不能把软件请求解释为物理停车，`UNCONFIRMED` 语义保持。这里的有限静态场景验证不替代真车制动、失联行为、动态避障或未知场景认证。

## 验收

依赖 P18/P19 已安装的 ROS 2 Jazzy、SLAM Toolbox、Nav2、Gazebo 和本机 SITL 构建。先显式指定要复用的本机 SITL 二进制目录（也可使用 OwnedSimulation 的默认本机构建）：

```bash
export VAF_SIMULATION_SITL_BIN_DIR="$PWD/artifacts/simulation/suite-e8ba09fa/build/ardupilot/sitl/bin"
./scripts/test_navigation_v1.sh
```

脚本先跑全量单元测试，再分别创建并清理独立世界，运行 tracking、cancel、map_loss、plan_change、timeout。单独一项：

```bash
python -m tests.simulation.path_following --allow-send --case tracking
```

场景使用真实 2160 线 Gazebo 激光，房间转角沿用 P18 的 0.15 rad，柱体位置为房间坐标 `(1.7,0.3)`，目标主动轮轴位置为 odom `(0.8,2.0)`。未知栅格不会被填充。Gazebo truth 只供被动测试 oracle，分别核对参考点路径、实际车体距柱体余量、到达误差、停车和最终权限；不会输入生产 Guidance 或 SLAM。

报告保存在 `artifacts/simulation/navigation-*/`，各项含原计划、Nav2 子进程 manifest、应用状态/Effect 事件、独立真值轨迹和所属进程/端口清理结果。
