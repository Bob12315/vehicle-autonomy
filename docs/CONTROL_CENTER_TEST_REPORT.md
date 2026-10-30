# 统一控制台与工具生命周期验收

日期：2026-10-30，Asia/Ulaanbaatar。项目根目录：
`/home/level6/vehicle-autonomy-framework`。开发分支：`codex/control-center-lifecycle`。

**本机验收通过。** 已交付 `./control-center`、统一 systemd 会话监管、本地工具注册表、
现有 Web 认证下的工具和系统控制页面、配置、自动化测试及说明。没有替换原
SimulationManager、Vehicle Spawner、SITL 所有者或车辆控制引擎。

## 审计与实现边界

审计覆盖 `app/web/action_cli.py`、`mission_control.py`、`app/simulation/manager.py`、
`universal_runtime.py`、`driver_worker.py`、`app/bootstrap/qgc_simulation.py`、
`app/tools/{local,process_worker,service,schema}.py`、`app/visualization/`、原认证与
控制页。此前手动多旋翼已结束，未接管历史实例，也未修改其他独立项目。

原仿真 Session 和 LocalTools 已有进程组、所有权标记、有限退出及审计；其上新增
一个**部署范围**的 systemd 用户服务/cgroup。原 LocalTools 负责注册工具的真实
进程启停，原 SimulationManager 继续拥有 World、车辆、SITL 与签名 Driver。
本轮没有建立第二套车辆或 Mission 管理器。旧远程 Agent 默认协议保持不变。

Server 保留 `gz sim -s -r --headless-rendering -v3 <owned-world>`；GUI 独立
`gz sim -g -v4`，复制选中 Server 的 GZ_PARTITION 和资源环境。
本机具备可访问 X11 `DISPLAY=:1`、XAUTHORITY、GPU 渲染设备、Gazebo、
提取式 ROS 2 Jazzy / RViz2 和桌面 QGC AppImage，路径均来自扫描或可信配置。
RViz 使用原三车型 Profile 与真实只读 ROS 桥。QGC 使用项目私有 Qt 目录与原单向
TelemetryMirror；参数查询/指令不会从 QGC 回传 SITL。

生命周期采用 `ExitType=main`、`KillMode=mixed`、`SendSIGKILL=yes`、
120 秒正常退出上限和 ExecStopPost。后台被 SIGKILL 后，systemd 清理全部剩余
cgroup 成员，后处理复用原 inode 所有权凭据销毁逻辑。异常退出记录
CRASHED / UNCONFIRMED，不能推定为安全着陆。浏览器在受管 cgroup 外打开。

## 真实本机结果

最后三轮完整桌面流程均 PASS：
`artifacts/control-center/acceptance-r5/` 、`acceptance-final/` 与 `acceptance-verified/`。
最后一轮包含“一键关闭全部工具但保留仿真”，并实际点击原车辆控制页的 RViz2 入口，确认复用同一工具所有者。测试使用真实 Chrome 窗口、原登录页、
真实 Web 按钮、Gazebo Server / GUI、ArduCopter、RViz2、QGC 和 systemd，未替换
遥测、进程管理、窗口状态或清理结果。

| 验收项 | 真实结果与证据 |
|---|---|
| 单命令启动 | PASS，默认 `./control-center`，自动打开浏览器；无场景、无工具、SEND 关闭 |
| 浏览器 Web / 登录 | PASS，真实 Chrome 登录 `/center`，与 `/simulation` 共用认证；无 JavaScript 错误 |
| 场景和车辆选择 | PASS，经现有页面选择 C01、固定 Copter 和出生点，创建并启动真实 World / SITL |
| Gazebo GUI 真正显示 | PASS，拥有的可见窗口、实时渲染 camera pose、地面及多旋翼截图；不是仅检查 PID |
| GUI 独立关闭 | PASS，Server / SITL 继续运行，车辆 ID、target 不变 |
| GUI 重新连接 | PASS，新 GUI PID、相同分区和 World，车辆实例不变 |
| RViz2 启停 | PASS，真实窗口和 OpenGL；原 ROS probe 验证当前车辆 TF、Odometry、Markers / Path 订阅 |
| QGC 启停和真实飞控 | PASS，QGC 原生日志识别 system ID 41、component 1、ArduPilot 3、Quadrotor 2；界面显示 Stabilize、卫星和电池 |
| 三种工具同时运行 | PASS，三个拥有的实际窗口同时就绪，PID / 子进程和资源快照已保存 |
| 独立关闭 / 重开工具 | PASS，关闭 RViz 或 QGC 时其他两个工具继续运行；重开成功 |
| 一键关闭全部工具 | PASS，三个工具及 ROS 桥退出，World 与车辆身份保持不变；全部重开成功 |
| 结束仿真保持控制台 | PASS，原 Manager 报告 FINISHED / cleanup COMPLETE，Web 继续运行 |
| 页面关闭整个控制台 | PASS，拥有的进程退出、相关端口释放，OS 后处理报告空成员、无凭据清理错误 |
| Ctrl+C 正常退出 | PASS，World-only + GUI 真实运行时退出并清理，非只检查空后台 |
| SIGKILL 后台 | PASS，三个图形工具 + 真实 Copter / Server 运行时强杀后台，内核清理整组，旧 PID / cgroup 无残留 |
| 启动终端异常消失 | PASS，强杀启动器，后台检测精确父进程身份消失并正常清理 |
| 重启与旧 epoch | PASS，四个不同控制台会话连续启动，端口不冲突、无旧实例接管；旧 epoch 请求返回 409 |
| 外部同名程序 | PASS，在控制台外另开真实 RViz2；关闭及强杀控制台后仍有可见窗口，最后由测试自己的所有者清理 |
| 个人 QGC 设置 | PASS，测试前后个人配置目录文件 SHA-256 完全一致 |

QGC 明确的真实连接日志：
`Adding new vehicle ... "UDP Link (AutoConnect)" 41 1 3 2`。
这是由本次真实 SITL 下行消息触发；窗口就绪本身不等于飞控连接。

四次最终退出的 `os-cleanup.json` 均记录 `remaining_owned_processes: []`、
`credential_errors: []`。强杀后台的一次记录 `SERVICE_RESULT=signal`、
`EXIT_CODE=killed`、`EXIT_STATUS=KILL`，对应状态 CRASHED，而不是伪造正常结束。
最终额外清理审计检查本轮所有 Session 记录的 PID / 启动身份、TCP / UDP 端口及
临时签名文件：**无存活受管进程、无占用端口、无签名凭据残留，服务 inactive/dead**。
端口数量和逐端口结果见 `artifacts/control-center/final-cleanup.json`。

## 现有功能回归

- `python -m pip install -e '.[mavlink]' -r requirements-vision.txt`：项目 `.venv` 安装成功。
- `python -m unittest discover -s tests -v`：最终 **920 / 920 PASS**，包含原 Framework、
  Mission、SimulationManager、Tool Agent、Workspace 和可视化测试。
- 新增 11 项合同测试覆盖操作认证、CSRF / Origin、另一控制页占用时拒绝全局关闭、
  旧 epoch、命令注入、图形会话缺失、锁、systemd 策略和崩溃后凭据销毁边界。
- 最后一轮原生 C01 动作回归：原 SetMode → Arm → Takeoff(1.5 m) → Goto → ReturnHome
  全部 SUCCEEDED；独立 Gazebo 真值确认运动和返航落地，最后已上锁且 cleanup COMPLETE。
  报告：`artifacts/control-center/copter-motion-regression/result.json`。
- 控制台原生浏览器流程中的 GetVehicleState 经原 Action Runtime SUCCEEDED。
- 普通 wheel 构建成功，已核验新模块、静态页面和配置入包。
  本轮便捷启动命令针对当前源码工作目录及其 `.venv`，未把安装 wheel 推定为外部机器部署验收。

本轮只复飞 Copter；Rover / Plane 的原生运动能力沿用此前限定验收记录，本轮没有重新
执行这两种车型的完整飞行/驾驶验收。其控制合同和软件回归包含在 920 项测试中。
没有新增硬件控制、生产连接、导航算法、VTOL 或飞控写入接口。

## 保留的失败和限制

早期真实失败均保留，没有覆盖为 PASS：首轮缺少 `/center` 登录返回白名单；
下一轮自动化等待表达式与现有 CSP 不兼容；随后 QGC 日志分类参数不匹配本机版本，
以及查询测试误用返回字段。均修复后重跑完整桌面流程。

后续回归发现给旧 Agent 实例增加 cwd 会违反严格消息 Schema；已把额外 metadata
限制在本地控制台日志模式，旧 Agent 默认报告未扩大。其原失败完整日志仍保留。
一次重叠启动多套同名 Alpha/Beta 测试 fixture 触发了原外部进程只读保护，也保留记录；
没有放松该保护。修复后的最终完整运行是 920 PASS。
第一次 wheel 配置出现重复 TOML 键，已合并配置清单，最终重新构建和核验成功。

本机 NVIDIA EGL 探测有警告，真实 Gazebo 画面和 RViz OpenGL 渲染通过，未将
警告当成渲染失败或伪报 GPU 型号。QGC 在线地图 / 地形请求可失败，不能以地图可用
作为本机遥测连接前提；单向连接也会使需要回传的参数/能力请求超时，未开放回传
来消除警告。纯 Wayland 无 XWayland 不支持当前 PID 窗口验证并明确报错。

未测试主机断电、用户级 systemd 自身崩溃、OS 内核失效、恶意工具主动逃出用户服务
或在其他操作系统的部署。其范围不包括真实飞机的失联安全认证。

## 证据与复现

```bash
./control-center --check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m tests.control_center.native artifacts/control-center/new-unique-run
.venv/bin/python -m tests.simulation.universal_native artifacts/control-center/new-copter-run C01 copter
```

原生测试使用私有、全新运行目录，最后一条会在**明确自有的本机仿真**内实际起飞和返航。
自动化会创建并关闭自己的桌面窗口，不连接实车。并行执行多套相同 Tool Agent fixture
会被原外部进程保护拒绝；完整回归套件应单独运行。

[使用说明](CONTROL_CENTER_GUIDE.md)；提交内的非敏感证据索引：
[control-center-evidence.json](control-center-evidence.json)。完整日志、截图和逐会话报告
保存在本机 `artifacts/control-center/` 与 `runtime/control-center/`，未把临时凭据加入 Git。
