# 仿真与当前程序一键启动

在仓库目录运行其中一个脚本（也可从其他工作目录通过绝对路径运行）：

```bash
./scripts/start_rover_sim.sh
./scripts/start_copter_sim.sh
./scripts/start_plane_sim.sh
```

| 入口 | 模型 | Web 控制页 | 系统 ID |
|---|---|---|---:|
| 汽车 | `target_rover` | http://127.0.0.1:8780/control | 1 |
| 多旋翼 | `iris_with_gimbal` | http://127.0.0.1:8781/control | 2 |
| 固定翼 | `~/twin-fixedwing` 的 `twin_cessna` | http://127.0.0.1:8782/control | 3 |

每个脚本启动自己的 Gazebo、ArduPilot SITL 和当前 Phase 4 Mission Control。
Phase 5 不接入；不会自动解锁、起飞或启动任务。固定翼仍只读使用外部双发模型、
跑道、相机和载荷插件；只在本次目录增加遥测与原生围栏参数，保持双电机原有
1000–2000 PWM 标定和空速设置，不修改 `~/twin-fixedwing` 原文件。

打开对应控制页，从终端打印的 `Access token file` 路径读取令牌并粘贴，点击“连接”。
令牌文件权限为 0600，不写入 URL、日志或 Git。等待约 45 秒，确认有有效、新鲜的
车辆状态。HTTP“已连接”本身不是可解锁的证明；执行仍由原有 SafetyPolicy 和执行链检查。

## 汽车基础控制顺序

1. 选择“设置模式”，设为 `GUIDED`，勾选本次 SEND 后执行。
2. 选择“解锁”，重新勾选本次 SEND 后执行，等待成功。
3. 在右侧勾选本次按住操控授权，按住 `W`/前进按钮；松开后等待停止确认。
   `S` 后退，`A/D` 左右转向；每一段按住操作均需重新授权。
   汽车停车后飞控保持 HOLD，下一段运动前先重新执行 GUIDED。
4. 独立动作“停止”也要重新授权。取消或发送停止请求本身不等于已经停车，
   以动作安全退出结果和实际速度为准。
   停止直接请求原生 HOLD，已在 HOLD 时可再次调用，不需要为停车切回 GUIDED。
5. 返航测试前先让汽车离开原点。可以选择“前往目标”，填 `x_m=2, y_m=0`，
   执行并等待到达，再选择“返航”。坐标采用 `odom`：X 向东，Y 向北，
   单位米；空白必填坐标会阻止提交，不会默认为零。
6. 等待返航成功、实际停车，再执行“上锁”。汽车测试范围保持原有 ±5 米围栏。

多旋翼需要先 `GUIDED`、解锁、起飞，再测试平移/转向/返航；Q/E 为升降。
固定翼使用原生起飞、引导目标、盘旋、RTL、自动着陆动作；飞行中“停止”不能
解释为悬停或空中停机。原生 RTL 配置/模式确认不代表已经回家着陆，飞行动作
沿用原有续接和 UNCONFIRMED 语义。双发模型的具体起降性能需单独人工验收。

固定翼控制页会把已确认的飞行续接 ID 放入下一次显式请求，无需手工复制；每次仍需
重新授权 SEND。地面仅提供 MANUAL 模式，先解锁再起飞，之后才使用空中模式。

## QGC、SEND 与退出

默认程序是唯一控制主体。QGC 监听本机 UDP 14550 可观察遥测；镜像只发送下行数据，
不接收/转发 QGC 的参数请求、模式、解锁或运动指令。Web 动作仍经过 Action、Execution、
Vehicle、Protocol、Transport，保留签名接收水位、Lease、TTL、会话和代际围栏。
启动阶段只对新建的自有 SITL 做公开签名配置、只读协议查询和参数读回，不做运动。

三个 shell 入口显式传入 `--allow-send`，仅授权本次本地仿真部署；系统与 Action SEND
初始仍为 false，Web 授权勾选初始也为 false。Python 通用入口不传该参数时为只读。
需要全程只读时给脚本加 `--read-only`；底层拒绝控制，即使 Web 勾选 SEND 也不会授权。

原先的独立 QGC 测试方式保留：`./scripts/start_rover_sim.sh --qgc-only`。
该模式不启动 Web 或框架控制链，QGC 直接操作自有 SITL；两种模式不并存于同一车型。

在启动终端按 Ctrl+C，或正常关闭本次 Gazebo 窗口：先让 Web 按现有机制退出控制，
再关闭本次仿真进程，确认进程组结束后删除登记的临时 EEPROM、签名文件和 Web 令牌。
日志及非秘密证据保存在终端打印的目录。不会全局杀进程或删除外部项目状态。

可选参数：`--headless` 不开 Gazebo 窗口；`--web-port 18880` 自定义 Web 端口；
`--qgc-port 14650` 自定义观察端口；`--duration 60` 限时退出；`--check` 只检查输入。
依赖、Python 环境、ArduPilot 和插件路径与 [独立 QGC 模式](qgc-start.md) 相同。
启动清单的 `ready` 仅表示服务已启动，不替代 EKF、安全状态或物理控制验收。

开发检查可运行 `python -m tests.simulation.program_launch --kind rover --motion --run-dir <新目录>`。
它从真实脚本启动程序，在 Chrome 点击操作，并通过只读 Gazebo 真值检查汽车的
前进、转向、停止、目标到达与返航。其他两种机型不加 `--motion` 时只验证启动、
新鲜签名遥测、逐次 SEND 拒绝、QGC 单向镜像和清理，不冒充飞行验收。

本次复验：三个默认 GUI 分支均通过真实启动与签名状态验证；汽车由 Chrome 实际
操作前进、转向、松开停止、Goto、Stop、ReturnHome、Disarm，并经独立 Gazebo
真值确认。汽车另验只读部署，原独立 QGC 模式验双向参数读取；退出均无残留进程
或临时凭据。全量单元回归 669 项通过（74.628 秒）。原始结果索引见
[验证记录](program-start-evidence.json)。该初次启动验收仅对汽车做运动测试；随后完成
三机型完整 Web HTTP 控制与双发起降复验，修复及当前证据见
[三机型 Web 控制复验](web-control-check.md)。人工飞行体验仍由操作者自行检查。
