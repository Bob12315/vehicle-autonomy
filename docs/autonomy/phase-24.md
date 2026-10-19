# P24：地图导航上的业务路线与对象巡检

2026-10-19。**PASS：本机原前驱 Rover 的地图路线与对象巡检范围。**

`autonomy:INSPECT` 读取严格、版本化的 Recipe，逐个提交注册导航目标。每个目标有独立 GoalNavigation、规划输入、路径准入、Run/Lease、停车和 Disarm；业务层没有车辆命令端口。完整状态与结果继续使用原本的本地 Application IPC。

本轮实现：

- 命名路线，最多 8 个已注册目标，明确总期限，目标失败后不继续下一个。
- 对象巡检：从有效 Observation 选择对象、核对已注册的 1–2 m 接近位置、地图导航、停稳并解除武装后记录观测，再继续路线。
- 结果包含检查点、导航任务 ID、尝试次数、对象/生产者/观测 ID、捕获时间、World revision 和 Frame epoch。
- 巡检前持续核对对象：置信度至少 0.5、odom 坐标、捕获年龄至多 0.5 s；丢失、过期、来源变化或移动超过 0.2 m 时取消导航，通过原 Stop 屏障后运行独立 Stop/Disarm 清理。清理不能确认时明确失败。
- 取消、总期限、Environment/epoch 和 Recipe 文件变化均有明确结果，不提交后续检查点。检查完成后的返程不要求目标继续存在。
- 导航配置可显式设置 `allow_reverse=true`，默认关闭。跟踪首次更新时冻结行驶方向；背向路径允许限速 0.10 m/s 的倒车，不强制执行 180° 原地掉头。最终 writer 对当前冻结参数再次检查倒车权限与范围，完整地图/时间/租约/Safety 检查保留。

使用既有 `--sim-sensor-config` 标准 Observation 输入。真实视觉、载荷释放及动态目标追逐不由这一业务组合自动获得支持；原 `object_inspection` / `cuadc_demo` 基线保留。本轮不重新宣称 YOLO 与地图业务的联合现场验收。

导航配置新增绝对 `recipes_path`，目标仍由 `goals_path` 提供。公开请求示例：

```json
{"mission":"autonomy:INSPECT"}
```

物理用例验证 `POINT_A → POINT_B → HOME`、巡检结果、对象消失和取消。这里的 HOME 在导航目标目录中显式注册为导航参考点的回家位置，不能与原 Environment 的车体 Goto 语义混用。对象接近点是预先登记的名义 1–2 m 点，不是自动生成的任意目标接近规划器。

## 已通过的正常闭环

`artifacts/simulation/goal-business_inspect-d854038a/`：78.153 s，3 个检查点、1 次观测，全部原生规划组释放。独立真值最大路径偏差 0.068 m；POINT_A、POINT_B、HOME 误差分别 0.157、0.167、0.156 m，各点线速度与角速度均为 0。实际倒车路程 2.292 m，由被动 Gazebo 真值测量，不输入控制器。

使用实际激光/SLAM 地图和 Gazebo 对象 Observation。场景把真实 marker `target_1` 放在 `(1.8,1.3)`；注册 POINT_A 为 `(0.4,2.5)`，名义距离约 1.844 m。低速 SDF 与 SITL 标定明确选择，见 [装配说明](../rover_autonomy.md)。默认车辆基线未替换。

## 最终故障与清理

| 场景 | 原始目录（`artifacts/simulation/`） | 结果 |
| --- | --- | --- |
| 正常三点巡检 | `goal-business_inspect-d854038a` | SUCCEEDED，3 点/1 观测，倒车 2.292 m，全部解除武装并关闭授权。 |
| 运动中取消 | `goal-business_cancel-92521ce2` | CANCELLED，2.603 s 确认停车；无检查点/观测，不进入后续地点，清理后 Disarm。 |
| 实际目标模型移除 | `goal-business_loss-57d9d41d` | FAILED，`inspection_target_lost_or_expired`，3.001 s 确认停车；无检查点/观测，清理后 Disarm。 |

三项源树指纹均为 `d606bbb1a5d92afe9ebd0fe41f9df16110a27eca8de38294546a0afaaf6e1be4`。原生规划组、所属进程和端口清理通过。正常任务黑盒记录了 102 个负速度目标，名义最小 −0.10 m/s（MAVLink float32 有通常的舍入尾差），与独立物理倒车路程相互核对。见 [便携证据](evidence/phase-24.json)。

6 项业务单元及 Application 公共入口预检测试通过；倒车、写前限制及相关集成测试纳入 260 项全量单元 gate，0 失败/错误/跳过。实现 `28c5e8e`，取消幂等补强 `904ded7`，最终装配/限速倒车 `4ff6790`、`827582f`。

保留的失败包括轮速积分/低速标定导致的期限保护，以及 180° 原地掉头越过路径保护（`goal-business_inspect-0f2de889`）。最终方案显式允许限速倒车；没有把旧失败改成成功，没有放宽 70 s 跟踪期限、0.15 m 运行偏差 guard 或 8 s 停车门槛。不声称任意航向、任意路径或其他底盘均可在这些期限内完成。
