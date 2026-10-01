# SITL 模式、解锁与上锁任务验收

> 状态：2026-10-01 本机 ArduCopter SITL 已通过。仅适用于数值 loopback TCP；不表示整车实机解锁、飞行或物理停止能力。

## 运行

先单独启动本机 ArduCopter SITL，使 TCP 5760 可连接。然后运行：

```bash
tests/manual_sitl_arm.sh runtime/sitl_arm.toml 'ArduCopter V4.8.0-dev (b5fbe265)'
```

直接入口为 `python -m app.main run-sitl-arm --config runtime/sitl_arm.toml --allow-send --allow-arm`。两个授权开关缺一时，CLI 在连接前拒绝。独立的 profile 强制 `127.0.0.1` 或 `::1`、ArduCopter 四旋翼、显式 Safety、周期和最长时限；配置文件不能开启 SEND。此 profile 在任务前等待 45 秒，给本机 SITL 的位置估计建立时间。等待并不绕过飞控预解锁检查：飞控仍可拒绝 Arm，任务会报告 `REJECTED`。

任务按顺序执行 `GUIDED` 模式 → Arm → Disarm。三个 Action 均只发一次 Typed Effect。每一步须由唯一 writer 写出，先得到 ACK，再看到**后续**未解锁目标模式、已解锁状态或未解锁状态，才进入下一步。新一步使用单独的 Run/Action Lease；双 SEND、Safety、会话、TTL 和写前栅栏继续生效。最终 SITL 翻译器只允许 Mode/Arm/Disarm，不提供 Takeoff、Land 或运动目标。模式任务原入口 `run-sitl` 仍只允许 Mode。

正常完成时，三个 Effect 都应经历 `REQUESTED → ACCEPTED → TRANSMITTED → ACKNOWLEDGED → COMPLETED`；最终 `SUCCEEDED`、`armed=false`、`disarm_cleanup=CONFIRMED`。任务失败或取消时，协调器在健康链路和新鲜状态下可发起**一次**受控 Disarm 清理并有界等待；解锁写入结果未知、断链或上锁无法确认时明确报告 `UNCONFIRMED_*`，不自动重放未知 Arm。模式/解锁任务没有活动运动流，不以此证明物理停止。

## 本次证据

本机 SITL 二进制包含 `ArduCopter V4.8.0-dev (b5fbe265)`；运行日志中版本由操作者提供，标记 `version_source=operator`。全新 SITL 进程以 `-M quad -O 47.397742,8.545594,488,0 -w` 启动后，45 秒等待的首次任务通过：三个 Effect 各得到 ACK 和新心跳状态，WorldSnapshot 修订号 416，最终 `SUCCEEDED`、`armed=false`、`disarm_cleanup=CONFIRMED`。此前 15 秒与 30 秒等待的首次请求被飞控以 `mav_result_4` 拒绝；30 秒记录中的 `STATUSTEXT` 为 `Arm: Need Position Estimate`。这些拒绝未被重试或计作成功。

`python -m unittest discover -s tests -q`：81 项通过。离线测试覆盖授权缺失、命令类型限制、三步状态门槛、飞控拒绝、取消后的受控上锁、断链未确认及解锁写入未知。`tests/manual_p6_sitl.sh` 原模式任务仍通过。没有修改 `legacy/cuadc_2026/`。
