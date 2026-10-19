# P23：地图、持久化坐标与定位来源可靠性

2026-10-19。**PASS：受审版本二维地图、同会话坐标锚点与定位来源审查范围。**

## A. 占据栅格上界

上游 [SLAM Toolbox #689](https://github.com/SteveMacenski/slam_toolbox/issues/689) 记录了边界缺失问题。本地审查 2.8.5 的 Karto `OccupancyGrid::ComputeDimensions`：栅格宽高按 extent 四舍五入，而 `WorldToGrid` 同样取整，最大端点可能正好落在 `index == size` 之外。

提供可复建的本地原生覆盖库，将宽高改为 `ceil(extent / resolution) + 1`。原始扫描与 ray tracing 不变，不补画障碍或空闲格、不钳制越界端点。原生反例：原版 156×156、丢失 2 个端点；修复 157×157、丢失 0 个端点。

覆盖库仅支持经审查的 **SLAM Toolbox 2.8.5**，构建时检查原始头文件 SHA，运行时检查覆盖库和原始两个运行库的 SHA。只为显式选择的 SLAM 子进程设置 `LD_PRELOAD`；不替换系统 ROS 文件。源码、上游出处和许可证见 `integrations/ros2/native/`。

```bash
./scripts/with_ros2.sh python -m integrations.ros2.build_slam_boundary --output-dir /absolute/new-build-directory
export VAF_SLAM_BOUNDARY_LIBRARY=/absolute/new-build-directory/libvaf_slam_boundary.so
```

实际轴对齐及 0.15 rad 旋转房间均已有四面墙的独立几何匹配和导出回读证据，运行日志确认调用了修复后的原生方法。限定这些二维场景，不扩大为任意建筑或现场建图质量保证。

## B. 地图锚点与目标语义

`MapAnchor` 持久化 Environment 内容哈希、HOME、车辆 Frame epoch、地图发布源 generation、登记地图内容/revision、map←odom 平面关系。`map` 目标必须配置绝对 `anchor_path`，目标明确表示已注册导航参考点的位置。

登记只允许新鲜地图、已验证原点、已观察停稳、Disarm 且双 SEND 关闭。文件有大小、普通文件、无符号链接及同一次读取的 SHA 检查。目标任务冻结锚点内容；地图内容可在同源后续 revision 正常演进，但仍经过当前地图整段路径校验和对齐约束。

```bash
python -m app.anchor --control-socket /absolute/app.sock --output /absolute/anchor.json
```

旧锚点在车辆会话、地图发布者或原点/HOME 改变后拒绝使用，必须显式重新登记及核对目标；不会自动把旧命名点投到新环境。持久化网格不自动成为定位或运动权限。**支持的重载流程须先停车、重启映射栈并重新登记；不支持外部绕过框架、在原 ROS 发布者中原地替换 pose graph 后继续使用旧锚点。**

## C. 单一活动定位源与只读候选

活动控制定位继续使用 `vehicle_reported_odom`，保留 VehicleState/Localization 同源版本不变量。新增 SLAM map-time TF 候选审查，检查源/Frame epoch、时钟、同一 map cut、版本回退或复用、过期和重定位跳变；跳变及来源切换需空闲重置。

候选没有独立验证的高频 twist，始终 `control_eligible=false`。≤0.5 s 的候选可标 VALID，随后为 DEGRADED，超过原地图期限则拒绝。没有平均 GPS 与 SLAM，也没有在运行中切换控制来源。

静止候选与场景真值一致只是数据链一致性检查；当前 TF 链与遥测里程计有关，**不代表独立 SLAM 定位精度或定位融合已完成**。实际运动定位仍由车辆独立真值验收覆盖。

## 验证

6 项新增单元测试覆盖锚点导出/重载、HOME/会话/发布源隔离、map 目标转换、锚点文件变化、候选质量/跳变及原生 ABI 拒绝。

| 最终用例 | 原始目录（`artifacts/simulation/`） | 结果 |
| --- | --- | --- |
| 轴对齐房间 | `map-reliability-0.0-a82cb4be` | 158×158 实际地图，四面墙独立匹配、导出回读、原生修复方法调用、候选只读均通过。 |
| 旋转 0.15 rad 房间 | `map-reliability-0.15-10e8b183` | 179×179 实际地图，同样四面墙/回读/只读检查通过。 |
| 注册 map 目标并执行 | `goal-map_goal-d593a063` | 轴对齐场景显式登记锚点后执行，SUCCEEDED，33.626 s；最大路径偏差 0.072 m、真实请求终点误差 0.160 m，停稳并 Disarm。 |

三项均使用最终修复库 `9edfc6ee2b7b8e4ed19fede848da5d7fc081c08a457140f97178cf38af3247f8`，源树指纹 `d606bbb1a5d92afe9ebd0fe41f9df16110a27eca8de38294546a0afaaf6e1be4`，所属进程/端口与原生规划组释放。见 [便携证据和构建 manifest](evidence/phase-23.json)。早期两项只读报告 `a4c49afc`、`1118cc24` 仍保留，未与最终库的报告混称同一次构建。

另对 5 个运动场景的 2447 份新鲜有效状态与被动真值进行采样时刻比对：活动车辆自报位姿最大 XY 差异 0.031 m 以下、yaw 差异 0.020 rad 以下。该比对包含报告/记录延迟，不是源时刻重建的定位精度认证；更不是独立 SLAM 基准。方法、原始状态日志 SHA 与逐场景结果见 [定位一致性记录](evidence/localization-status-crosscheck.json)。

实现 `a26c6bc`；配套时钟/TF 等待、低速真实动力学装配和请求端点连接见 `102355b`、`4ff6790`、`827582f`。最终根目录单元 gate 为 260 项通过。没有因本阶段通过而启用 SLAM 控制定位、自动重定位融合或硬件时钟同步。
