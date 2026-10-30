# Vehicle Autonomy Framework

面向自主移动平台的可复用框架。主程序唯一位于 `src/vehicle_autonomy/`，
外部软件使用本机安装，项目只保存接入配置、自有场景和必要适配代码。

## 安装与启动

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -e '.[mavlink]' -r requirements-vision.txt
vehicle-autonomy status
vehicle-autonomy-hardware --check
```

普通入口不连接车辆。硬件当前保持只读，`hardware_controlled` 会被拒绝。
可选 ROS 依赖只进入明确启动的工作进程，基础导入和普通单元测试不要求 ROS。

在 `environments/tools.local.toml` 中填写本机软件路径；首次配置可复制模板：

```bash
cp environments/tools.example.toml environments/tools.local.toml
vehicle-autonomy-environment check
./control-center
```

已有本机配置时直接使用，不覆盖原文件。Gazebo、ArduPilot SITL、QGroundControl、
ROS 2 和 RViz2 独立安装在仓库外；程序不在普通启动时下载整套软件。
详细字段、覆盖优先级和工作进程环境见 [环境索引](environments/README.md)。

`./control-center` 是安装后的 `vehicle-autonomy-control-center` 的薄入口。
默认允许明确自有的本机仿真部署授权，页面 SEND 仍关闭，需操作员显式开启。
只观察使用 `./control-center --read-only`。进入仿真中心选择场景和车辆后再启动，
GUI、RViz2、QGC 按需打开。关闭控制台只清理本次自有进程；异常退出由 systemd
用户服务负责 cgroup 清理。QGC 在框架组合中仅接收遥测。

## 目录与职责

| 位置 | 内容 |
| --- | --- |
| `src/vehicle_autonomy/` | 七模块程序、Web 静态文件、框架维护的原生适配代码 |
| `environments/` | 外部软件与资源索引；模板提交，本机配置不提交 |
| `configs/` | 程序业务配置、安全策略、车辆及显示配置 |
| `simulation/` | 自有模型/场景/任务/参数和第三方资源锁定清单 |
| `scripts/` | 薄启动入口和显式开发、部署、测试工具 |
| `tests/` | 单元、集成、界面和本机仿真验收 |
| `docs/` | 架构、操作指南、验收报告和历史记录 |
| `runtime/state/` | 持久状态、认证配置、工作空间锁 |
| `runtime/sessions/` | 每次运行的实例、进程归属、会话及日志 |
| `runtime/logs/`、`runtime/cache/` | 日常日志与可重建缓存 |
| `artifacts/` | 测试及导出结果，正常启动不依赖此目录 |
| `.venv/` | 本项目 Python 安装环境 |

七模块为 `contracts`、`engine`、`actions`、`vehicles`、`world`、`autonomy`、`app`。
职责、软件边界和迁移要求见 [文件组织规范](docs/FILE_ORGANIZATION.md)。
版本化资源支持源码安装和 wheel，不依赖调用者当前目录；外部资源集使用
`VAF_RESOURCE_ROOT`，本机环境索引使用 `VAF_ENVIRONMENT_CONFIG`，可写运行根使用
`VAF_RUNTIME_ROOT`。显式用户输入的相对路径仍相对调用目录。

第三方大型资源及软件副本已迁到仓库外，本机位置由环境索引记录。
历史验收数据单独归档，迁移清单和实测结果见 [整理报告](docs/WORKSPACE_LAYOUT_REPORT.md)。
持久状态和执行日志不作为普通缓存批量清空；Web 审计沿用现有日志轮转。

## 使用入口与验证

- [控制中心](docs/CONTROL_CENTER_GUIDE.md)、[仿真中心](docs/SIMULATION_WEB_UI_GUIDE.md)
- [车辆基础仿真](docs/simulation/program-start.md)、[Mission Studio](docs/MISSION_STUDIO_USER_GUIDE.md)
- [ROS 2 操作流程](docs/ROS2_OPERATOR_WORKFLOW.md)、[只读硬件部署](docs/hardware_deployment.md)
- [当前实现边界](docs/architecture.md)、[硬件审计](docs/HARDWARE_READY_AUDIT.md)
- [历史开发与验收概览](docs/history/DEVELOPMENT_OVERVIEW.md)

```bash
python -m unittest discover -s tests -v
node tests/web_console_smoke.cjs
```

真实 SITL/Gazebo 回归由 `tests/simulation/` 中的显式入口运行，只使用自有 loopback
仿真实例。软件路径来自统一索引，验收结果不能扩展为实机安全认证。

[系统行为基线 V1.0](Vehicle_Autonomy_V1.0.md) 和
[七模块归属基线 V1.1](Vehicle_Autonomy_File_Structure_V1.1.md) 继续有效。
目标能力不等于当前已实现能力；本次文件整理不新增车辆写入通路或未来功能。
