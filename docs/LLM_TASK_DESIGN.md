# 仿真中的 LLM 任务编排

当前提供两种显式仿真入口。默认 `training` 保留原 ±5 m 训练围栏和单任务组合；
`yard` 使用单独的 ±15 m 场地、匹配的 Safety/Environment、低速车模控制参数、
装卸点、巡检点、静态车辆/货架与可见场地边界。提示词不能自动扩大围栏。
两者都只连接自行创建的 localhost SITL，不连接机载电脑或 USB 飞控。

## 打开增强演示

已有私有 LLM 转发时不重复启动；会话重启后需要建立：

```bash
ssh -NT -L 127.0.0.1:19436:127.0.0.1:11436 bob@10.10.12.240
```

配置 `config/llm.server-tunnel.json` 对应实际检查过的协议和模型。其他服务器须
提供真实配置，不能猜地址或模型名。

```bash
./scripts/simulation_console.sh --scenario yard --gui --allow-send \
  --llm-config config/llm.server-tunnel.json --lifetime-s 1800
```

初始化后输出 `http://127.0.0.1:8766` 和本次私有 token 文件路径。
在页面认证后选择示例、点击“填入示例”，或自行输入任务意图；点击“设计任务组合”，
检查步骤、参数与预检，勾选人工确认后批准。示例按钮只填文字，不生成或执行任务。
Gazebo 显示同一辆仿真车。Ctrl+C 受控关闭，或到期自动关闭自有进程。
关闭受管 Gazebo 窗口也将结束本次自有仿真栈。
省略 `--allow-send` 拒绝任务，省略 `--gui` 只运行后台仿真。

可输入：

- `前进10米，再以半径1.5米向左绕完整1圈，速度0.15米每秒，然后停车。`
- `以0.15米每秒去DOCK，停留2秒，然后回HOME。`
- `以0.15米每秒依次去A、B、C、HOME，在B停留2秒。`
- `原地向左转720度，然后停车。`
- `前进1米，左转90度，右转90度，然后回HOME，速度0.15米每秒。`

“一直转圈”需要补充有限圈数、半径和方向。越界、已知障碍占用的站点、预算超限、
未知能力及非法参数不会因为模型建议而获准执行。`SERVICE_BAY` 故意被静态车辆占用，
用于验证拒绝；它不是可用装卸点。

## 已注册参数化能力

| 能力 | 参数与边界 | 行为 |
| --- | --- | --- |
| `motion:drive` | distance_m 0.2–10；speed_mps 0.08–0.18 | 沿批准时的计划朝向前进 |
| `motion:turn` | angle_deg −1080–1080，绝对值至少 5° | 正为左转/逆时针，负为右转；原地定角旋转 |
| `motion:circle` | radius_m 1.5–3；laps 整数 1–3；direction left/right；speed_mps 0.08–0.18 | 有限绕圆；参数组合仍受时间和碰撞预算限制 |
| `motion:wait` | duration_s 1–30 | 停车停留；不表示已完成视觉识别 |
| `motion:visit` | 已注册 waypoint；speed_mps 0.08–0.18 | 在清晰直线通道中到达站点 |

每个子任务都走原 Mode/Arm/Typed Action/Effect/Stop/Disarm 链；运动建议没有
MAVLink 或传输端口。前后步骤需要释放 SEND/Lease，并连续观察到新鲜的静止
Disarmed 遥测。全局最多 8 步、600 秒，单个机动最多 300 秒。
停止点/转向对齐只允许在受限区域内做不超过 0.05 m/s 的小幅前后修正。
0.15 m 横向偏差和 500 ms 定位新鲜度门槛保持不变。

参数由 Application 的能力目录决定，LLM 不能增加字段、生成任意坐标、代码、
PWM 或 MAVLink。Schema 2 每一步为 `{"mission":"motion:drive","parameters":{...}}`；
旧 Schema 1 的无参数任务组合仍兼容。参数化任务不能与不透明旧路线混合。

审批预览把相对任务一次性展开成绑定当前会话、场景与源 epoch 的绝对计划。
批准时车辆相对预览移动超过 0.1 m 或转动超过 0.1 rad，将要求重新设计。
预览 60 秒有效；批准后一次消费，重复 HTTP request ID 不重复执行。
运行中不能无声地把路线重新锚定到新位置。

## 场景与安全范围

场地、站点和障碍分别在 `simulation/environments/yard.toml`、
`simulation/scenes/yard.json`。场景构建器从同一已审静态配置生成 Gazebo 碰撞模型。
Application 校验整个轨迹的车体占用和已知障碍；原唯一 writer 再检查状态、
源文件、路径偏差及一秒扫掠预测。Stop 不因场景或运动拒绝而被拦截。

这是已知静态场景的任务与控制验证，尚无当前场景的 live LiDAR/Nav2 动态避障或
自动绕路能力。不要把 GUI 手动移动/添加障碍后的世界当作仍已验证的静态配置。
模型没有实时几何信息，理由文本不是安全验收；执行资格取决于确定性预检。
空间可视化继续由 Gazebo/ROS/RViz2 承担，Web 负责计划审阅、任务和状态。

参数化组合取消或失败后，在原子任务结束并释放权限后，只允许注册的 Rover
`safe_recovery` 做 Stop/Disarm，清理不自动恢复下一步。清理最多 30 秒；不能确认
时显示 `FAILED / cleanup_unconfirmed`。旧无参数组合保留 10 秒清理预算。
遥测失联不等于已物理停车。真实车辆的控制、制动和独立物理急停仍未验收。

## 可复现验收

```bash
./scripts/test_practical_scenarios.sh artifacts/simulation/yard-suite-NEW
```

串行执行真实模型准入/拒绝、前进与左右转向、DOCK 往返、多点巡逻、绕圆、
720° 旋转、运动中取消及只读重启/旧提案隔离。每项独立创建场景，保留原始失败、版本、任务 ID、
模型提案、ACK/状态、独立 Gazebo 真值、清理与端口释放记录。没有并行 Gazebo
争用，不跳过失败用例。批准字段在此脚本中是明确的仿真测试输入，不授予硬件权限。
最终额外执行不导入控制器的轨迹审计，从实际 world.sdf 和被动 Gazebo 真值
检查路径偏差、静态碰撞体间距、停留速度及自有资源释放。单个功能 PASS
不能覆盖整套回归中的 FAIL；偶发原生进程崩溃也保留为失败证据。

旧无参数链回归仍可运行：

```bash
./scripts/test_llm_design_simulation.sh artifacts/simulation/llm-design-NEW
```

API 使用认证、CSRF 与 Host/Origin 保护：`POST /api/design {"text":"..."}`；
`POST /api/design/approve {"id":"...","human_approved":true}`，批准须携带
`X-VAF-Request-ID`。Web 不拥有 writer。

实际结果、剩余失败与版本以最终审计及可移植证据为准。本场景验收不覆盖 P26
未解决的 Nav2 跟踪失败，也不代表真实车辆已具备这些能力。
