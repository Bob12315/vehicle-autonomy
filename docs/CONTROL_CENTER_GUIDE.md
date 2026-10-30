# 统一本地控制台

在项目根目录执行：

```bash
./control-center
```

需要已经按 README 安装 `.venv`、Gazebo Harmonic 和固定车辆库所需的本机
ArduPilot / Gazebo 插件。入口使用项目独立环境，检查用户级 systemd，启动原有
MissionControl 与 Web，自动打开 `http://127.0.0.1:8780/center`。使用本机已设置的登录密码；首次未配置时，启动终端会引导设置。
终端打印本次日志目录，不打印密码或认证密钥。所有页面复用原来的登录、CSRF
与 Origin 校验。默认没有车辆、场景、图形工具或 SEND。

进入“仿真中心”，选择 World、固定车辆模型和出生点，创建后点击启动。
就绪后可直接点击“打开 Gazebo 三维窗口”，也可回到“本地控制台”选择当前 World
并打开工具。已有 `/control`、`/studio`、`/console` 保留，侧栏均有控制台入口。

默认启动已允许手动操作**自有本机仿真车辆**，以下两条命令等价：

```bash
./control-center
./control-center --allow-send
```

这只允许原部署授权；车辆页的 SEND 开关仍默认关闭。仅观察时使用
`./control-center --read-only`。修改启动参数需要退出旧控制台后再启动，不会原地提升旧仿真实例的授权。车辆指令继续经原
Action、Execution、Safety、Authority、唯一 MAVLink Writer，Lease / TTL / session /
generation 与物理退出不确定性不变。QGC 本轮只观察遥测，不能借此控制车辆。

如果从原“车辆总览 → 工具管理”进入，本机控制台模式会直接显示“本机工具已由控制台管理”
及本机工具中心链接。无需注册远程代理程序；等待不会自动启动未配置的远程代理程序。

## 三种工具

- **Gazebo GUI**：Server 仍由原 SimulationManager 用 `gz sim -s -r --headless-rendering`
  管理；按钮仅启动 `gz sim -g -v4`，复用选中 World 的分区、资源路径和环境。
  关闭 GUI 保留 Server、SITL 和车辆实例；重新打开连接相同 World。更换 World
  使用原仿真中心的新 epoch 切换流程，不为开窗口重置车辆。
- **RViz2**：自动读取已安装 ROS 2 环境，复用三车型
  `configs/rviz/{rover,copter,plane}-visualization.rviz` 和原只读遥测可视化桥。
  选中车辆后显示真实 TF、Odometry、GPS 和实际轨迹；点云、Map、外部 Path
  没有已验证输入时保持关闭并提示缺失。未选择车辆可开空白观察窗口，不生成假数据。
  独立 ROS worker 才导入 ROS 依赖，基础后端不导入 ROS。
- **QGroundControl**：扫描 PATH、桌面、下载、Applications、用户 bin 和 `/opt`，
  也支持可信配置指定绝对路径。AppImage 使用原生 extract-and-run。
  配置、缓存和数据只写 `runtime/control-center/qgc/`，不修改个人
  `~/.config/QGroundControl/`。默认接收 `127.0.0.1:14550` 的原有单向
  TelemetryMirror；排除 SETUP_SIGNING，UDP 输入没有回到飞控的路径。
  飞控状态以真实 QGC 界面为准；窗口就绪与遥测连接分开解释。
  参数下载、改参、Mission 上传和飞控命令需要双向交互，本监视连接不提供这些功能。

工具可以单独打开、关闭、重启，也可以“关闭全部工具”而继续运行仿真。
结束仿真保留控制台；绑定该 World/车辆的 Gazebo、RViz 窗口随依赖结束关闭。
QGC 可独立保持打开，失去遥测后不表示飞控仍在线。

真实窗口检查使用 X11 / XWayland 的窗口 PID、映射状态和大小；Gazebo 还需收到
渲染事件产生的 GUI camera pose，选车 RViz 还需原真实 ROS TF/Odometry/订阅检查。
无可访问 DISPLAY、Qt offscreen/minimal 或缺少检查工具时拒绝声称 GUI 成功。
**纯 Wayland 无 XWayland 当前不支持窗口所有权验收**，页面明确报错。
GPU 设备、DISPLAY、XAUTHORITY、Wayland 和 ROS 环境诊断见系统详情。

## 退出与所有权

Ctrl+C 或“关闭整个控制台”会先停止接收新任务，调用原应用、任务和仿真退出流程，
随后关闭辅助工具。若另一车辆控制页仍保留控制权，Web 关闭请求会拒绝，并提示
先在原页安全退出、释放 SEND。物理停止不能确认时仍保留 UNCONFIRMED。

后台在按项目路径唯一命名的 systemd 用户服务内运行，使用独立 cgroup、
`ExitType=main`、`KillMode=mixed`、`SendSIGKILL=yes` 和 120 秒正常退出上限。
正常先通知主进程走原清理；主进程退出或被 SIGKILL 后，操作系统清理整个剩余
cgroup，包括另建进程组的工具子进程。不是只靠 finally / atexit。

`ExecStopPost` 记录 OS 清理结果，确认组内其他成员退出后，复用原
OwnedCredentials 的 inode 检查清除本次 SITL 状态与临时签名凭据。异常退出记录
CRASHED / UNCONFIRMED，不把进程消失当成真实车辆安全着陆。旧运行目录不接管、不
恢复 SEND；每次有新的控制台、World 与车辆身份。工作目录文件锁与唯一 systemd
unit 防重复启动。启动终端异常消失也由后台身份监视触发清理。

浏览器由启动器在受管 cgroup 外打开，已有个人浏览器和外部同名图形程序不随控制台
退出。所有停止均针对本次实际拥有的记录、管道、进程组或 cgroup，绝不按程序名全局杀进程。

## 配置与诊断

```bash
./control-center --check                 # 只检查安装与图形环境
./control-center --port 8785             # 改 Web 端口
./control-center --no-browser            # 不自动开浏览器
./control-center --config /abs/host.json # 可信本机配置，不能经浏览器修改
```

默认配置为 `configs/control-center.json`。可以指定工具绝对路径、白名单 argv、环境、
工作目录、ROS wrapper、Framework 工作空间 setup 与 QGC 端口。`executable: null`
表示扫描，`cwd: null` 表示创建本次工具私有工作目录。默认优先使用现有
`scripts/with_ros2.sh`；本项目存在 `install/setup.bash` 时自动叠加，其他工作空间通过
`workspace_setup` 显式配置。可选依赖缺失显示原因，不自动安装系统软件。

浏览器只提交工具 ID、启停枚举和当前 World/车辆 ID，不接受 Shell、argv、环境或路径。
工具配置通过原 Tool Manifest 校验。运行目录中 `tool-registry.json` 记录实际命令、
ROS 环境、依赖、健康检查、停止策略、工作目录与日志位置；工具原始日志按 8 MiB
保留当前与一个历史文件。页面只读注册工具的有界尾部日志。

每次证据在 `runtime/control-center/cc-*/`：`state.json`、`backend.log`、
`http-audit.jsonl`、`tool-registry.json`、`tools/logs/`、原 `application/simulation/`
会话报告及 `os-cleanup.json`。`runtime/control-center/current.json` 指向最近一次运行
的元信息。网页登录密码以带随机盐的 PBKDF2-SHA256 校验值保存在私有 `password.json`，不保存明文。
更改密码：关闭控制台后执行 `./control-center --set-password`，再重新启动。
`operator.private` 仅供内部 API 自动化使用，无需用户读取或输入，不能代替网页登录密码。

当前系统必须有可用的 Linux 用户级 systemd / cgroup；没有时启动失败并解释原因，
不退回到无法保障崩溃清理的运行方式。

生命周期设计依据：[systemd.kill](https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html)、
[systemd.service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)；
Gazebo Server / GUI 分离依据：[Gazebo Sim](https://gazebosim.org/libs/sim/)。
