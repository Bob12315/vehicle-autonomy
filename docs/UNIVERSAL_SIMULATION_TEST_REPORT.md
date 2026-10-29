# 通用固定车辆与 World 解耦验收报告

测试：2026-10-29 至 2026-10-30（Asia/Ulaanbaatar）。范围是自有本机 Gazebo Harmonic 8.15.0、锁定 ArduPilot SITL 和现有
Framework 控制链。未连接真实车辆。所有数字来自本机原始运行记录；静态准入、启动健康、
物理运动和浏览器验证分别计数。

## 交付与兼容数量

| 固定车辆 | 静态准入 World | 实际加载与 Framework 健康 | 实际运动 World | 实际 Web World |
|---|---:|---:|---:|---:|
| Rover 1.0.0 | 22 | 6 | 5 | 5 |
| Copter 1.0.0 | 22 | 9 | 4 | 7 |
| Plane 1.0.0 | 6 | 3 | 3 | 2 |
| VTOL | 0，BLOCKED | 0 | 0 | 0 |

22/22/6 是经过实际几何、地面、跑道、固定安全围栏和资源 SHA 检查后的准入数量，
不是已经完成这些数量的运动测试。全部 60 World × 4 Vehicle 的 240 行状态见
[完整兼容矩阵](UNIVERSAL_WORLD_VEHICLE_MATRIX.md)，含 World-only 历史证据的来源说明。
[机器证据索引](simulation/universal-evidence.json)记录固定指纹、关键参数公开回读、
原始结果路径、SHA、失败实验与每个单元格的判定。

本轮已交付固定车辆库、纯实例绑定、独立 World 出生注册表、一个 Gazebo 内最多四个
独立 SITL/控制 owner、多车增删、受控 World 替换与原登录下的 Web 集成。模型、
传感器、参数和 Framework profile 不按 World 修改。每车 owner 在自有进程中运行原
VehicleActionDriver/Execution/Safety/Authority/唯一 MAVLink Writer，父进程没有私钥
或新的车辆命令端口。原两个 SEND 门、Lease/TTL/session/generation 和 UNCONFIRMED
语义保留。架构细节见 [系统架构](SIMULATION_SYSTEM_ARCHITECTURE.md)及
[固定车辆库](VEHICLE_LIBRARY.md)。

## 指定的十一组原生运动

| 固定车辆 | World | 实际流程 | 结果 |
|---|---|---|---|
| Rover | R01、R04、R06、R03 | GUIDED、Arm、受管前进、原停止退出、Disarm、独立位姿/速度检查、清理 | 四组 PASS |
| Copter | C01、C02、C04、C05 | GUIDED、Arm、1.5m 起飞、Goto、ReturnHome/着陆、独立位姿/速度检查、清理 | 四组 PASS |
| Plane | F01、F02、F03 | 模式与解锁/上锁、50m 跑道起飞、GUIDED 转弯、LOITER 保持飞行速度、RTL 实际接近、AutoLand 着陆上锁 | 三组 PASS |

上述基础控制统一使用 seed=0、obstacle_count=0、无风及默认摩擦；场景固有建筑、地面和地形仍保留。这不构成随机障碍避让或恶劣风场验收。

Rover/Copter 最终原始结果在
`artifacts/simulation/universal-20261029/final-{World}-{kind}/result.json`；
Plane 最终统一签名时钟结果在同目录的 `causal-F01-plane`、`causal-F02-plane`、
`causal-F03-plane`。各车型跨地图的 version/fingerprint/model/parameter/sensor SHA
分别完全一致。关键参数另通过已有的签名公开参数回读验证，未读取 EEPROM 或更改
参数来通过地图。原生飞控/EKF 的 45 秒预热保留，READY 不被当作可立即解锁或运动通过。

这十一组之外，三车型混合浏览器测试还实际让同一 Rover 在 F01 前进并安全退出。
加载健康所覆盖的额外组合来自实际双车/三车/四车启动和换图，未提升为没有执行过的
飞行或运动验收。

## 真实多车与 Chrome

| 同一 World 的实例 | World 切换 | 浏览器流程 | 结果 |
|---|---|---|---|
| Rover + Copter | R01 → R04 | 原控制页控制 Rover、其他车保持静止、单车移除/添加、换图、导出、清理 | PASS |
| Rover + Rover | R01 → R03 | 同上；两台独立身份与端口 | PASS |
| Copter + Copter | C01 → C04 | 原控制页起飞/降落第一台，第二台保持静止；增删、换图、清理 | PASS |
| Plane + Rover + Copter | F01 → F02 | 三车型同时存在，控制 Rover，Plane/Copter 地面静止；精确识别新增车、换图 | PASS |
| Rover + Copter + Rover + Copter | R01 → R03 | 四实例、当前车只读查询、控制隔离、增删、换图、导出与清理 | PASS |

实际 Chrome 共用原登录 cookie/CSRF；从 `/simulation` 打开 `/control#target` 后不重复
输入密钥，不自动开启 SEND。每车有唯一实体名、target、System ID、端口、SITL、owner、
签名身份、状态与日志。换图后所有 target/session/generation 更新，版本和指纹保留，
SEND 为关闭。单车移除保持同一 Gazebo 和其他实例继续运行，新增车获得新身份。
浏览器没有 JavaScript 错误，真实日志、报告下载和最后清理通过。

最终浏览器记录为 `browser-rover-copter-r9`、`two-rovers-r2`、`two-copters-r2`、
`browser-mixed-three-qualified` 和 `browser-four-qualified`，都在本轮 artifacts 目录。
桌面/移动静态界面另有真实 Chrome 检查；最终车型中文标签经过只读 Chrome 检查。
截图是运行证据，场景缩略图仍明确标为示意图，不冒充实时渲染。

独立的 Gazebo pose/info 历史进一步复核控制隔离：三组 Rover 控制的最大实际位移约
0.446m、0.485m、0.296m，四车 Rover 约 0.175m；双 Copter 中受控机实际升高约 1.535m。
所有未受控实例的最大位移为 0，详见
`artifacts/simulation/universal-20261029/multi-ground-truth-audit.json`。
这些是一个受控实例运动、同伴静止的测试，不宣称协同编队飞行或多机避碰已实现。

无车 R01 另通过真实加载、时间推进、暂停、恢复、重置与清理；静态 World 无需等待车辆 pose 主题，原无车工作流保留。结果为 `world-only-final/result.json`。

## Epoch、故障、Mission 与清理

`stress-r2` 连续运行六个新 epoch：R01 → R04 → R06 → R03 → R01 → R04。
每轮通过原 Action 发出 HOLD，捕获真实签名 ACK 与遥测，再把上一轮原始字节注入新
实例的接收故障边界。新 key 的签名验证拒绝旧 ACK/遥测，未刷新新状态或继承 SEND。
六轮 target/session/generation 各不相同，固定指纹与关键参数一致，全部旧进程和凭据
退役。父进程 RSS 从约 41.8MiB 到 48.1MiB；包含首次 MAVLink 解码模块导入和保留的
六轮历史，不能据此宣称无限时长无内存增长。

原接收故障测试在独立 owner 方案下再次 PASS：实际 20ms 延迟、观察到的丢包、冻结
原签名字节均经过真实链路。冻结产生 115 次 replay 拒绝，随后触发失联/过期围栏与清理，
没有通过重写时间戳保持健康；物理停止仍是 UNCONFIRMED。该故障不代表 SITL EKF 内部
GPS/IMU 融合故障。

`query-missions` 在 Rover 与 Copter 两个独立 target 上通过原 Mission runtime 执行
GetVehicleState，两个 Mission 均 SUCCEEDED/release_safe，两个 SEND 门保持关闭。
本轮没有新增 ROS/Tool 服务部署或感知算法的验收结论。

最终对本任务全部成功和失败实验的 **205 份 World/Vehicle 自有会话清单**进行核对：
没有存活自有进程、僵尸、自有进程组成员、未结束清单或残留签名凭据；实例 40..100
共 305 个 TCP/FDM/内部 UDP 端口检查均可用。审计只读取 PID/start_ticks/进程组，不接管
或终止未知进程。结果为 `cleanup-audit.json`，状态 PASS。大型运行证据留在忽略的
artifacts，未把第三方资源、凭据或 2GiB 原始运行数据提交 Git。

## 回归与修复证据

隔离环境完成要求的 editable/mavlink/vision 安装。最终
`python -m unittest discover -s tests -v`：**909 项 PASS**；JavaScript 语法检查 PASS；
wheel 构建和 World 出生表、车辆表、VTOL 审计、worker 模块的打包检查 PASS。
完整单测日志为本轮 `unit-final.log`。主要修复均保留失败实验，没有删除后改写为 PASS：

- 原启动器只支持 R01/C01/F01；现改成固定定义和统一动态实体/SITL 生命周期。
- 删除服务 ACK 只是排队确认。现在保持 SITL FDM 存活，独立观察实体消失后再结束 SITL，
  避免锁步插件阻塞共享 World。
- UI/大历史及 GC 曾跨越 owner 周期；现将 owner 放入每车受管进程，历史摘要与原始 JSONL
  分离，未关闭 GC、扩大超时或修改安全阈值。
- 固定速率时钟在低 RTF 下逐渐过期。所有车型现在统一使用已有的签名 TIMESYNC 与
  20ms owner 周期；Plane continuation 的原就绪循环也使用同一周期。三张 Plane 地图
  均以此最终策略重新完成全航线。过载至原心跳/周期阈值时仍失败关闭。
- 接收故障可能触发共享 World 退役，因此也检查所有相关控制页的所有权，防止间接停止另一页面的车辆。
- 退休窗口增加 Web 与 owner 双重准入屏障，旧 UNKNOWN 安全障碍不被展示截断隐藏。
  动态新增按实际同伴位姿重验，部分失败可回滚；持久化失败不阻止清理。
- 原生浏览器脚本修正了过早取消 Disarm、重复 selector，以及三/四车中新增实例的精确识别。
  这些失败原件也在索引中保留，不当作产品运动通过。
- 自定义 Plane heading 的跑道检查使用旋转后的全长走廊，不只检查起点或正向轴框。

## 仍明确阻塞或未验收的能力

官方确有真实 QuadPlane 候选：已固定提交检查 `skywalker_x8_quad` 的模型、四升力电机、
Q_ENABLE/Q_FRAME 参数和 SDF；官方还提供 Alti Transition 的外部装配。**VTOL 仍 BLOCKED**，
因为 Framework 专属控制/安全/模式过渡和原生起降过渡未验收，部分资产许可也未完成追溯。
没有把 Twin Cessna 重命名为 VTOL。来源、SHA 和阻塞项见 [车辆库说明](VEHICLE_LIBRARY.md)。

R05/C06 的动态碰撞包络、未审查的上游复杂网格/地形出生点继续 BLOCKED；Plane F05/F07
因跑道障碍阻塞。Rover/Copter 固定 ±5m 控制围栏保留，远侧预设超界时拒绝；不同地理
原点/旋转坐标系尚需合格 Environment 绑定。安全换图/单车移除要求已上锁、地面静止且
原安全屏障已释放；空中或未知状态明确失败，须通过原控制页完成返航/降落/上锁。

意外 SITL 退出可能卡住共享 lockstep World，不能宣称任意进程崩溃后仍物理隔离。
摄像头、气压计/磁力计数据管线、外部传感器、碰撞事件采集、GPU 和本轮未运行的
Tool/ROS 任务保持 NOT_TESTED/未知，固定模型内存在配置不表示数据管线已经工作。

使用步骤见 [Web 指南](UNIVERSAL_SIMULATION_WEB_GUIDE.md)，结构化请求见
[Manager API](SIMULATION_MANAGER_API.md)。所有实际运动继续走原控制页或原授权
Action/Mission 入口，仿真中心的测试按钮只执行所选车的只读查询。
