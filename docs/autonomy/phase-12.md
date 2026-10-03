# P12 基础 Action：PASS

基线 P11 `2674d61`。注册有限 Arm/Disarm/Takeoff/Land/Goto/ReturnHome/Hold/Stop，参数锁定 Environment，Action 只持不可变世界和结果，Mission 获得专用只读 WorldReader。每步独立租约、双 SEND、Safety、唯一 writer 保留。

Arm/Disarm 等待后续 heartbeat；起飞/落地须 ACK 加新鲜高度、速度及稳定时间。导航持续受限请求，退出 Stop 的后续状态确认和 2 s 稳定屏障后才进入下一步；8 s 退出失败报 UNCONFIRMED。断链失败撤销控制，禁止旧流重播。

验收命令：`python -m unittest discover -s tests -q`；`./scripts/test_simulation_v1.sh --build-dir artifacts/simulation/suite-e8ba09fa/build`。

完整证据 `artifacts/simulation/suite-6f5cf91c/summary.json`：149 tests、17 阶段、11 场景 PASS，0 失败/跳过；Copter/Rover 从正式 app CLI 启动 action_probe，独立 Gazebo 判定起飞、命名点、HOME、Stop、落地、上锁。原五个车辆场景、P9/P11 场景全部保留；清理自有进程/端口成功。

保留失败：`suite-d5210812`、`autonomy-rover-31aa7065`、`autonomy-rover-df09fecf`。原生 Rover 位置导航在返航转向后误差超 0.75 m；重写有限 body 导航，选择较小转向的前进/倒车，加入实际角速度阻尼和 0.45 m 内部到达余量。最终验收容差仍 0.75 m、导航截止 45 s，未放宽。Rover Hold 使用零速；停止后撤销授权。

仅 localhost speed-one SITL/Gazebo；不构成真实飞行/停车证据。P13 完整路线和中途取消/状态过期另行验收。
