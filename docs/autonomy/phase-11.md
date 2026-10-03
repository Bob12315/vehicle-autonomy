# P11 Versioned Environment

状态：**P11 PASS**。基线 P10 `9cc584c`，日期 2026-10-03。

格式冻结为 TOML schema 1，SI 米、显式 odom ENU。不可变 Environment 包含 configured geodetic origin/source、HOME/source、矩形围栏、命名位置、search 区域。资源 content SHA256 与当前 WorldModel frame epoch 共同形成 generation，revision=1；目标解析结果携带具体 ResourceReference。未经会话绑定不解析目标，未知 HOME/名称、缺失 source、重复名称、异 Frame、越界点/区域、Safety 围栏不一致均拒绝。

`simulation/environments/{copter,rover}.toml` 中 HOME=(0,0,0) 是明确的训练场配置，非未知原点的默认值。移动预检通过飞控自身 local/global pose 对照配置原点；无 GPS fix 证据不认为原点已验证。GPS_RAW_INT 在显式仿真参数中要求 5 Hz EXT_STAT；不发硬件参数命令。Copter 的 HOME_AIR 是显式命名的返航悬停点，不把地面 HOME 当作空中 Goto。

Application 绑定资源并发布 WorldSnapshot.environment 和 Environment dependency，状态显示版本、Frame、home/origin 来源及名称。运行中配置内容变化立即清空资源、撤权/结束旧任务并降级，必须重启预检；重连有新 frame epoch，旧解析目标不可复用。Environment 是数据源，不能替代 VehicleSafetyPolicy。

单元：`python -m unittest discover -s tests -q`，143 tests PASS；新增资源错误、origin 改变、热切换、同版快照、重连和围栏一致性检查。

进程/物理：正式 App 的两车状态/任务/重连回归；`tests.simulation.environment_probe --kind copter|rover --allow-send` 先按资源名称解析再走原 Execution/Authority/Safety/writer，不在脚本指定目标坐标。两车到 A、返回 HOME/HOME_AIR、Stop 均由独立 Gazebo Oracle 判定，使用原 0.75 m Goto、8 s Stop、2 s 稳定门槛。Copter 最终落地，Rover 最终 Disarm。此阶段不宣称 P12/P13 Typed 运动 Action/Mission 完成。

失败诊断：首个 Rover HOME probe 超时（`artifacts/simulation/environment-rover-88e7df82/`），仍停在 A 附近，停止确认/清理成功。日志表明反向 waypoint 距离约 2 m 而位置导航没有产生有效转向；使用已验收的受限 body-yaw stream 显式对齐再发位置目标，45 s 总导航截止不增加。重跑 Rover A/HOME 真值误差约 0.54/0.60 m，满足原门槛。首次全套 `suite-5af9786a` 因原点证据未就绪拒绝；补齐仿真 GPS fix 发布和最多 3 s 等待后重跑，保留失败报告，未降低容差。

当前完整命令：`./scripts/test_simulation_v1.sh --build-dir artifacts/simulation/suite-e8ba09fa/build`，加入两车 named-resource probe，原五个正常/故障场景全部保留。

最终报告：`artifacts/simulation/suite-863c8818/summary.json`，143 tests、15 阶段、9 场景全 PASS，零失败、零跳过。两车正式 App、命名点、原完整车辆正常与故障场景和所有清理均通过。

阶段实现提交：`2674d61`；后续完整软件组合回归与补强见 [完成审计](completion-audit.md)。
