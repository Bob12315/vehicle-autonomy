# 工作区整理报告（2026-10-30 至 2026-10-31）

整理基线为 `9167fb8`，开始前工作区干净。用户要求正式程序统一在 src，外部软件使用
仓库外本机安装，仓库只保存索引、配置、自有资源及必要适配代码。

## 改动

- 增加 `environments/tools.example.toml` 与统一 HostEnvironment；实际机器索引忽略 Git。
- 仿真中心、三车型入口、控制台、Tool Registry、ROS 包装入口共用软件索引。
- 移除正常程序对 artifacts 软件来源和个人绝对路径的默认引用。
- RuntimePaths 区分 state、sessions、logs、cache；wheel 使用用户可写 state 根。
- 迁移控制台密码、私密 token、QGC 设置、锁和现有持久状态，保留 inode/权限。
- 控制台最终清理同步迁移到新目录，保留目录归属校验和原有凭据销毁机制。
- World 工具和视觉 fixture 的实现迁入 src，原命令保留为薄入口。
- 根 README 收敛为当前安装和使用入口，原完整开发概览存入 docs/history。
- 私密 Tool Registry 和其生成 SDF 中的旧软件/运行目录引用按迁移映射更新，
  不重写 Mission journal、签名水位或历史验收原件。

## 本机数据迁移

本次迁入一个新建且独立的用户数据目录：
`~/.local/share/vehicle-autonomy/workspace-layout-20261030/`。

`software/` 保存原仓库内的受测 ArduPilot、Jazzy、ARM64 Humble、World/视觉资源和
原生适配构建结果；`archive/` 保存历史 artifacts 和 World 验收原件。
迁移为同文件系统重命名，原始内容未批量删除。软件并未重新下载或替换版本。
已有 `~/ardupilot`、Gazebo 插件工程、固定翼工程与原用户 ROS 安装的源码未被修改。

实际依赖位置、Git 版本和三车型程序 SHA256 在本机 tools.local.toml 中记录。
完整逐项映射在该外部目录的 `migration.json`，并复制到本次 artifacts 证据目录。
当前密码和认证文件已转入 runtime/state/control-center，历史会话保留在
runtime/sessions；旧历史文档中的 artifacts 路径可通过迁移映射查找。

这是工作区分离与归档，不等于释放了同等大小的整机磁盘空间。

## 验证

最终验证通过：

- `python -m unittest discover -s tests -v`：943 项，123.510 秒，无失败或跳过。
- R01 Rover / C01 Copter / F01 Plane 真实本机 SITL/Gazebo：全部 PASS，
  清理均 COMPLETE。Plane 包含原生起飞、目标、盘旋、RTL 和 AutoLand。
- R05 / C06 World smoke：L1/L2 PASS，不扩展为这些 World 的车辆运动验收。
- 三车型启动入口 `--check --headless` 通过；ROS/RViz2 初始化与 `--check` 通过，
  这不是新的 GUI 映射窗口验收。
- 真实 systemd 用户服务只读启动、READY、正常关闭通过，无剩余自有 cgroup 进程；
  密码文件沿用迁移后的持久配置，没有重新创建密码或接管旧 PID。
- wheel 457 个条目、915,930 字节。全新隔离环境安装后，从仓库外目录运行 status、
  hardware --check、环境检查和控制台帮助通过；写入根位于用户 state 目录。
  包含环境模板，不包含本机索引、软件副本、runtime 或 artifacts。
- 24 个 Shell 入口语法检查通过；页面 JS 冒烟保留任务审批和 CSRF 行为检查并通过。
  本机没有独立 node 命令，实际使用已安装 Playwright 的 Node 22.18.0。

首次三车型回归因绝对 Gazebo 路径与其 basename 进程标题不一致而被归属围栏拒绝。
修正只规范化该发行版启动器的已知标题表示；错误 World、被改动的参数和 SITL
路径替换仍被拒绝，PID、start_ticks、PGID、cwd、会话和凭据校验保持原样。
失败原件与最终 PASS 原件分别保留，没有覆盖或删除失败证据。

原 JS 测试夹具仍假定已移除的 token 输入框，现改为使用实际共享登录客户端，
验证 cookie 会话和会话 CSRF；生产页面没有改动。本检查明确不代替浏览器视觉验收。

本机证据和摘要在 `artifacts/workspace-layout-20261030/`。清理打包缓存后，
工作区由约 22.34 GiB 降至约 1.60 GiB；剩余主要是 .venv、Git 和保留的 runtime。
历史记录、第三方软件和资源仍占用仓库外的磁盘，不能把迁移量当作整机空间释放量。

本轮没有重新运行 ARM64 板端、Python 3.10 矩阵和完整 SLAM/Nav2/P26 物理验收。
Humble 保留原 ARM64/Ubuntu 22.04 平台限制和依赖搜索路径，不声称新硬件支持。

本次不增加实机运动、Plane 新指令、ROS 控制权限或任何未来能力；
已有 Phase 5 / P26 限制和历史独立 FAIL 结论继续有效。
