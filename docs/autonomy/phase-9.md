# P9 Application Runtime

状态：**P9 PASS**。基线提交 `662a586`，工作区初始干净；基线 125 tests PASS。日期 2026-10-03。

冻结范围：仅 `copter_sim`/`rover_sim` 数值 loopback 配置；本机 Unix socket 一行 JSON 用例请求，8192 字节、16 客户端、1 秒处理期限，socket 0600；不接受 Effect/MAVLink/授权配置。重复 mutation request ID 缓存结果，内容冲突拒绝；缓存满后拒绝新 mutation，不淘汰后重执行。

```bash
python -m app.main run --profile copter_sim --allow-send
python -m app.main ctl --profile copter_sim status
python -m app.main ctl --profile copter_sim start --mission disarmed_mode
python -m app.main ctl --profile copter_sim cancel
python -m app.main ctl --profile copter_sim shutdown
```

`--config` 只在 run 入口接受，经严格 SimulationProfile 验证；`--control-socket` 指定端点。默认 SEND 关闭，无任务也关闭。MissionRuntime Envelope 的 Run/Action/Effect/期限直接进入 VehicleExecution，不重新构造身份；Deployment 对编译步骤授予租约。任务只允许未解锁 Copter GUIDED、Rover HOLD，以 ACK 和后续状态为成功条件。模式任务 15 秒截止，失败不自动重试。

连接失败有界退避 0.2–2 秒；运行期保持可查询。断链由车辆 Runtime 撤权；旧任务失败，重连生成新 world/session epoch，只读恢复。取消不会宣称撤回已经发送的模式命令。SIGINT/SIGTERM 与 shutdown 共用有界清理；不删除预存或 inode 不匹配端点。

验证：`python -m unittest discover -s tests -q`，136 tests PASS（包括原有测试、身份链/零写出/过期/重连和真实无 SITL CLI 进程）。完整回归 `./scripts/test_simulation_v1.sh` 新增两车正式 App 子进程场景，沿用原五个物理/故障场景和数值门槛。

失败诊断：首次完整运行 `artifacts/simulation/suite-e8ba09fa/` 构建和单元通过；进程场景发现 argparse 对 `ctl --profile … start` 的可选位置参数解析失败。改用 `parse_intermixed_args` 并补真实 CLI 测试，未放宽验收条件。新运行重用该自有 build 目录，保留首次失败报告。

不覆盖真实设备、Web/onboard、定位正式链、Environment 或运动 Mission。

最终证据：`artifacts/simulation/suite-6f961663/summary.json`：13 个阶段、7 个场景、136 单元测试、零失败、零跳过，进程组与端口全部清理。额外重跑更新后的两车 App 场景均 PASS（`artifacts/simulation/application-*/summary.json`），包括 fresh Oracle 存在检查。

阶段实现提交：`c80a18b`（包含 Application/CLI/IPC/进程验收）。
