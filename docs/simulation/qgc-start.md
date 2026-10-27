# 三车型独立 QGC 仿真启动（`--qgc-only`）

启动脚本现在默认还启动 Web；本页描述显式 `--qgc-only` 的原有独立模式。
Web 操作见 [当前程序基础控制](program-start.md)。

用于人工检查 Gazebo + ArduPilot SITL 环境。三个启动文件互相独立，默认打开
Gazebo 画面。车辆操作由用户在 QGroundControl 中执行，不启动框架 Web、Mission、
Action 或 Phase 5，不连接实车，不自动解锁、起飞或运行任务。

在仓库根目录运行任意一个：

```bash
./scripts/start_rover_sim.sh --qgc-only
./scripts/start_copter_sim.sh --qgc-only
./scripts/start_plane_sim.sh --qgc-only
```

| 启动文件 | 模型 | QGC 系统 ID | SITL instance / JSON UDP |
|---|---|---:|---|
| `start_rover_sim.sh` | 本仓库 `target_rover` 汽车 | 1 | 11 / 9112 |
| `start_copter_sim.sh` | 现有 AP Gazebo `iris_with_gimbal` 多旋翼 | 2 | 12 / 9122 |
| `start_plane_sim.sh` | `~/twin-fixedwing/models/twin_cessna/model.sdf` 双发固定翼 | 3 | 13 / 9132 |

固定翼使用该项目的 `twin_runway.sdf` 和 `config/twin.parm`，保留双发、常规尾翼、
已有相机与水瓶插件。不是本仓库此前的 `plane_runway` 单发模型。
外部项目只读使用，不调用其 `start.sh`/`stop.sh`，不修改其模型、参数或原有状态。

## QGroundControl

1. 在本机打开 QGC，启用 UDP 自动连接，监听默认 **14550**；若关闭了自动连接，
   手动添加 UDP 连接并设置监听端口 `14550`。
2. 运行所需车型脚本。三种车型均将 MAVLink 发往 **127.0.0.1:14550**，
   SITL 的原生 `udpclient` 接口同时接收地面站回复，不需要 MAVProxy 或第二个框架 Writer。
3. 等待传感器/GPS/EKF 初始化，通常需要约 20–40 秒，以 QGC 的实际状态为准。
   脚本打印“Waiting for QGC”仅表示进程已启动，不是解锁条件或飞行验收通过。
4. 在 QGC 检查机型、姿态、定位、参数和手动操作。三个脚本可以分别在三个终端启动，
   QGC 通过不同系统 ID 区分；同一车型的重复启动会拒绝，不会杀掉已有实例。
5. 在启动终端按 **Ctrl+C** 关闭该次仿真；正常关闭 Gazebo 窗口也会结束该次会话。
   只清理脚本自己登记的进程组，不使用全局 `pkill`。

本入口是独立人工地面站仿真环境，不授予框架 SEND/Lease，也不修改其默认安全门。
不要把此入口的人工地面站控制方式理解为框架内部新增了直写飞控通道。

## 环境及参数

先按 README 在独立 Python 环境安装本项目。脚本优先使用 `.venv/bin/python`，
兼容当前开发环境 `.venv-migration/bin/python`；也可显式设置 `VAF_PYTHON`。
与调用终端的当前目录无关。

默认读取本仓库隔离 ArduPilot 构建 `artifacts/phase2-control/ardupilot-source`，
不存在时使用 `~/ardupilot`；Gazebo 插件/多旋翼模型来自
`~/gz_ws/src/ardupilot_gazebo`。固定翼还需要 CMake、C++ 编译器和已安装的 Gazebo
开发依赖；每次在本次运行目录内编译原项目的 `TwinPayload.cc`，避免复用不兼容的
旧 `libTwinPayload.so`。脚本不会安装系统依赖或改动外部项目的构建目录。

```bash
# 只检查文件、二进制和端口，不启动仿真
./scripts/start_plane_sim.sh --qgc-only --check

# 后台计算环境，不打开 Gazebo 窗口；仍在本终端运行，Ctrl+C 停止
./scripts/start_copter_sim.sh --qgc-only --headless

# QGC 自定义监听端口时同步指定
./scripts/start_rover_sim.sh --qgc-only --qgc-port 14560

# 覆盖只读输入位置
./scripts/start_plane_sim.sh --qgc-only --twin-root /path/to/twin-fixedwing \
  --ardupilot-root /path/to/ardupilot --plugin-root /path/to/ardupilot_gazebo
```

每次运行在 `artifacts/simulation/qgc-车型-时间-随机值/` 生成新目录，保存模型副本、
参数副本、全新 EEPROM、日志和 `session.json`。不会继承上次 QGC 修改的参数；
有需要时请自行从 QGC 导出。`runtime/qgc-simulation/` 只保存各车型启动锁。
固定翼场景、AP 参数和二进制等输入的 SHA-256 记入运行 manifest。

## 开发验证范围

真实测试入口只接收遥测并发送 `PARAM_REQUEST_READ`：

```bash
.venv-migration/bin/python -m tests.simulation.qgc_launch --kind rover \
  --run-dir artifacts/simulation/qgc-check-UNIQUE/rover
```

三车型实际检查心跳类型/系统 ID、姿态、全局位置、双向参数读取、未解锁状态、
原输入文件未变及退出清理；固定翼额外核对 `SERVO3_FUNCTION=73` 和
`SERVO6_FUNCTION=74`。这些检查不操作解锁、模式、起飞、运动或参数写入，
也不冒充用户后续的 QGC 人工运行/飞行验收。

首次实现（提交 `41af096`）的三个 GUI 启动分支均完成真实遥测/参数读取、资源加载错误检查、重复启动
拒绝和 SIGTERM 清理。原始运行位于 `artifacts/simulation/qgc-launch-final/`，
源码摘要和结果索引见 [验证记录](qgc-start-evidence.json)。本次没有在 QGC 界面解锁或飞行。
当时完成该实现后的全量单元回归为 665 项通过，75.202 秒；日志保存在该证据根的 `unit.log`。

早期固定翼运行仅通过链路检查，随后日志复核发现外部旧载荷插件依赖缺失的
`libprotobuf.so.23`，因此不作为完整启动通过证据。旧原件保留；改为本次运行目录
隔离编译插件后的复验通过，原外部二进制也未被覆盖。
