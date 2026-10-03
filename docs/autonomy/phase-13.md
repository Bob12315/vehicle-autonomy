# P13 命名基础 Mission 验收

状态：**PASS，限 localhost SITL/Gazebo 仿真。**

前置 P12 `951e94e`；非车辆合同独立提交 `ca4df82` 不影响车辆路线。Copter/Rover 的 basic_route 用严格 TOML 注册步骤、Environment 命名 A/B/HOME、STOP 策略、max_attempts=1。预检完整参数、能力、环境/定位、起点未解锁和仿真 warmup；safe_recovery 可在重连后新授权执行，不需要重新等待 motion warmup。

正式 App CLI 连续两次正常路线已通过：Copter `autonomy-copter-b2574695`，Rover 最终 `autonomy-rover-554a5bd9`。两车中途取消与状态过期、重连只读通过：最终 `suite-3501a226/copter_mission_faults`、`suite-3501a226/rover_mission_faults` 的 summary/status/proxy 日志保留；`mission-faults-copter-c64802a9` 保留为初始化真值过期的失败记录。取消需 Stop COMPLETED、独立 Gazebo 速度达标、双 SEND 关闭；过期时 FAILED/UNCONFIRMED，新 epoch 无旧命令重播，显式 recovery 再落地/上锁。

保留原 0.75 m 导航误差、45 s 导航、8 s Stop/2 s 稳定门槛。Rover 使用较低角速度增益/阻尼、逐渐减速和前进/倒车方向选择，内部到达余量 0.45 m。连续任务暴露 EffectResult 查询全历史扫描引发 O(n²) 周期超时，改为按 ID 查询，200 项历史测试证明查询有界，保留原周期超时保护。Gazebo 已限定 loopback/每场景独立 partition，避免宿主 Wi-Fi 切换破坏测试订阅；见官方 Transport environment variables 文档。

单元/合同测试全绿；P12 完整回归 `suite-6f5cf91c` 全绿。P13 全套 `suite-330d6a45` 的模式、环境、Action、Copter 两次路线通过，但 Rover 因宿主网络中断真值过期而失败，未把该报告标绿。最终全套 `suite-3501a226` 的两车路线各连续两次、取消/过期/重连与原车辆场景全部通过；29 阶段、21 场景、173 项当时单元测试全绿。最终补强后的单元/合同测试为 177 项，详见 [总审计](completion-audit.md)。不宣称实机。

取消/关闭补强：Execution 在保留退出 Stop 租约的同时取消当前 Action 尚未 TRANSMITTED 的队列请求，避免取消先到、下一周期仍写出 Arm/Takeoff/Land。已发送 one-shot 结果不改写为取消，副作用不能撤回。队列取消与已发送不可撤销合同测试通过。

阶段实现提交：`ad9a5fa`；取消队列补强独立提交 `0afe6be`。完整复现命令：`./scripts/test_simulation_v1.sh --build-dir artifacts/simulation/suite-e8ba09fa/build --timeout 3600`。
