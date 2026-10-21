# 仿真中的 LLM 任务设计

LLM 可以设计最多 8 步、总运行期限 600 秒的任务组合。每一步只能引用
Application 已注册、且 Web 启动时列入 `--missions` 的能力。
例如 `disarmed_mode → basic_route → disarmed_mode`；配置了命名目标和巡检
配方时也可以引用 `navigate:POINT_A`、`autonomy:INSPECT`。
LLM 不创建任意坐标、代码、速度、循环或车辆指令。

Web 中输入任务意图，点击“设计任务组合”，检查 JSON 步骤和预检结果；
预检通过后勾选人工确认，再点击“确认仿真提案”。预检失败会显示具体原因。
地图、点云、TF 和路径继续使用 ROS/RViz2。

提案 60 秒后失效，一次批准后不能再次执行。提案绑定车辆会话、环境、
能力目录和配置指纹；批准时在 Application 事件循环内重新检查。
运行期环境、会话或能力改变会取消组合，不能从断线处自动续跑。
每步通过原 Mission/Action/Effect/Safety/Lease/唯一 writer 执行。
进入下一步之前要求子任务结束、SEND/Lease 释放，以及至少 3 次不同采样、
持续 300 ms 的新鲜静止且 Disarmed 遥测。遥测不得超过 500 ms。
清理不能确认时标记 `FAILED / cleanup_unconfirmed`，不能称为实车停车证明。

本接口仅接受明确的 `*_sim` Application；硬件只读组合没有执行入口。
模型推理运行在 Web 请求线程，不占用 Application 实时循环或取消锁。
模型服务离线时本地正在执行的任务及安全链保持独立。

## 一键验收

先建立已授权服务器的私有 SSH 转发（已有同端口转发时无需重复启动）：

```bash
ssh -NT -L 127.0.0.1:19436:127.0.0.1:11436 bob@10.10.12.240
```

`config/llm.server-tunnel.json` 对应实际检查过的服务器协议及模型。
其他服务器须提供真实配置，不能照搬端口或模型名。

交互式体验（独立生成车模，不会自动启动任务）：

```bash
./scripts/simulation_console.sh --allow-send --llm-config config/llm.server-tunnel.json
```

约 45 秒初始化后输出 `http://127.0.0.1:8766` 和本次 token 文件路径。
在本机读取该文件并粘贴到页面认证，输入
“先执行 disarmed_mode，再执行已配置的 basic_route，最后再次执行 disarmed_mode”。
检查步骤、预检和确认框后批准。`basic_route` 的实际路线在
`simulation/missions/rover.toml`，目标在 `simulation/environments/rover.toml`。
该交互入口只有基础路线；需完整 mapping/Nav2 装配才能使用命名导航能力。
默认 900 秒后受控结束；Ctrl+C 提前退出。未给 `--allow-send` 时拒绝任务。
它不连接机载电脑或 USB 飞控，也不将真实传感器接入该车模。

```bash
./scripts/test_llm_design_simulation.sh artifacts/simulation/llm-design-NEW
```

该脚本明确授权测试自己的 localhost SITL，启动独立 Gazebo、Application 和
认证 Web，真实调用配置的 LLM；检查模糊/不安全/未知目标、两步重复任务、
实际路线移动与 HOME 返回、人工批准协议、CSRF、重复请求、取消、重启隔离，
并保存源码版本、模型提案、任务结果、Gazebo 独立真值和清理证据。
`--hold-only` 是 Python 模块的显式诊断选项，只能声称停车模式链验收。
脚本退出时关闭自己创建的进程，不连接物理飞控。

API：`POST /api/design {"text":"..."}` 返回提案和预检；
`POST /api/design/approve {"id":"...","human_approved":true}` 批准。
后一请求必须携带 `X-VAF-Request-ID`；认证、CSRF、Host/Origin 检查与原任务 API 相同。

本功能的测试结果见最终审计；它不改变 P26 已记录的导航失败，也不代表实车验收。

实际运行组合版本 `848064d`，完整单元测试 322 项通过、0 跳过；两轮真实模型
端到端路线组合通过，HOME 误差约 4.4 / 4.0 cm。
原始日志在 `artifacts/simulation/llm-design-20261021-r3` 和 `r4`，可移植的版本/
断言/日志 SHA 在 `docs/autonomy/evidence/llm-task-designs.json`。
早期两轮失败也保留，没有覆盖。
取消实测位于步骤边界；运动中组合取消和组合 Nav2/巡检仍未完成实测。
无法在取消后 10 秒内观察到静止且 Disarmed 时显示清理未确认，不自动进入下一步。
