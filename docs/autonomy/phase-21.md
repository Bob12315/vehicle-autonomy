# P21：命名目标导航

2026-10-19。**PASS：本机 Rover 二维仿真范围**。

Application 公开用例 `start {mission: "navigate:POINT_A"}` 读取显式版本化目标目录，以当前 WorldSnapshot 的定位、Environment、地图和坐标代际组织后台规划、最新地图准入、原 `follow_path` Mission 与物理停车。目标明确表示导航参考点在 odom 中的位置；没有静默改变 HOME 的含义。

规划线程只持有不可变输入；Nav2 在所属原生进程组执行。取消、超时、配置/代际变化后，晚到结果不能启动车辆。关闭先隔离车辆请求，再等待规划组退出。规划期间双 SEND 保持关闭；实际执行仍通过原双授权、Lease、Safety 和唯一 writer。

## 验证

- 全量单元测试：230 passed；新增 7 项覆盖目标配置、非阻塞任务、取消/晚到结果、输入代际隔离和准入。
- `goal-tracking-b7f91da4`：实际 SLAM + Nav2 + Application + SITL/Gazebo，2.316 m / 44 点折线路径，最终 SUCCEEDED。独立真值最大路径偏差 0.128 m、终点误差 0.075 m、停车速度 0.016 m/s 以下。
- `goal-planning_cancel-ff7af3ca`：规划期间取消，CANCELLED，无运动 Effect、无授权、无位移，原生规划组释放。
- `goal-unreachable-e224ef19`：未知/障碍目标被准入预检拒绝，FAILED，无武装、无移动。此例在原生后端启动前被拒绝，不能称为原生后端无路搜索验收。
- 所有场景原始数据与清理 manifest 在 `artifacts/simulation/` 对应目录；提交的证据摘要见 `evidence/phase-21.json`。

复现：设置 `VAF_SIMULATION_SITL_BIN_DIR` 后运行 `python -m tests.simulation.goal_navigation --allow-send --case tracking`（或 `planning_cancel`、`unreachable`）。应用启动需显式 `--navigation-config`，其 `goals_path` 为绝对路径。示例目录由验收脚本生成，默认配置仍不启用导航发送。

开发中一次状态响应重复嵌套完整 Effect 历史，超过 Unix socket 单次发送窗口，导致 ROS 探针超时并安全停车；已去掉重复内容，未放宽地图有效期。失败目录 `goal-tracking-195d8dbb` 保留。

P20 的 70 s 跟踪期限、8 s 停车屏障、未知空间阻挡、速度和横向偏差限制保持。更多朝向/连续任务及第二车型由后续阶段补充；本阶段不声明任意长路径、动态避障、最终朝向或实机支持。自动重规划仍关闭。
