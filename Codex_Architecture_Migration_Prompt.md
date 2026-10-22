# Codex 指令：Vehicle Autonomy 七模块文件架构迁移（仅迁移，不开发新功能）

你现在是负责本地仓库迁移的资深 Python/ROS 2/ArduPilot 软件工程师。请在**当前这一轮工作中直接检查、实施、测试、修复和提交**。不需要先给我抽象方案，也不需要询问已在文档中明确的设计选择。

## 0. 项目位置与权威文档

- 工作仓库：`/home/level6/vehicle-autonomy-framework/`
- 系统行为/安全与目标架构基线：`/home/level6/vehicle-autonomy-framework/Vehicle_Autonomy_V1.0.md`
- 本次目录规范：`/home/level6/vehicle-autonomy-framework/Vehicle_Autonomy_File_Structure_V1.1.md`

先完整阅读上述两个文档以及仓库的 `README.md`、`AGENTS.md`、`docs/architecture.md`；如个别路径不存在，先在项目内核实实际文件并清楚记录，不要猜测。优先遵守本次七模块文件结构规范；对于系统行为与安全边界，以 V1.0 总体架构为准。**不得改写、覆盖或删除这两个架构文档。**

## 1. 唯一目标

只完成**文件架构迁移**：将当前分散的顶层 Python 模块规范化到 `src/vehicle_autonomy/` 下七个包：

1. `contracts/`：数据与接口合同
2. `engine/`：Mission/Action 运行机制、控制授权与 Safety
3. `actions/`：所有可编排 Action（含直接适配 ROS 2、Nav2、SLAM、VLM API 的 Action）
4. `vehicles/`：ArduPilot/MAVLink、Rover、Copter、未来 Plane 的车辆归属
5. `world/`：传感器、感知、定位、建图、World Model
6. `autonomy/`：可复用规划、Guidance、Intelligence 算法
7. `app/`：Web、CLI、Operator、场景任务、应用装配

**不建立** `capabilities/`、`adapters/`、`integrations/` 这些独立顶层业务包；外部生态的客户端和转换代码按功能所属的 Action、World 或 Vehicle 模块就近安置。并非所有 ROS 2 节点必须成为 Action：持续数据采集归 World，供 Mission 明确调用的能力才是 Action。

根目录保留：`configs/`、`simulation/`、`tests/`、`scripts/`、`docs/`、`.github/`，以及必要的 README、文档、项目配置。要求 `pyproject.toml` 和可安装的 `src` 包布局有效。

同时按照用户明确要求，**删除仓库内** `/home/level6/vehicle-autonomy-framework/legacy/` 目录。不要修改或删除此目录以外的历史项目位置；尤其不得操作任何独立旧项目目录。先确定 `legacy/` 未被当前运行和测试依赖，再完成移除并记录。

## 2. 严格范围约束

这次是架构和包路径迁移，不是功能研发。禁止顺手增加/重构下列功能：

- 新增 ArduPlane/Plane 实际控制、测试物理模型或 VTOL 支持；
- 实现 Mission Graph 的 Parallel/Condition/Event/Recovery 新调度算法；
- 新增 Resource Manager、抢占算法或修改控制权/安全语义；
- 新增或改写 Nav2 导航、SLAM 控制、VLM/LLM 任务能力；
- 连接真实飞控发送指令，启用任何 `hardware_controlled` 入口；
- 修改飞控参数、运动控制律、速度和围栏限值；
- 为提高测试通过率而删除、屏蔽、放宽测试，或更改不可通过的验收阈值。

保留原有系统的 **双 SEND 默认关闭、Lease、TTL、时间/Frame/版本/来源检查、唯一 MAVLink writer、Stop/Cancel 的 `UNCONFIRMED` 语义、HardwareReadOnly 入口的禁写性质**。不能因目录调整破坏这些保证。

此外，禁止只创建新目录树却不完成导入、启动、资源路径和测试迁移；禁止仅复制源码、保留新旧两套并行实现；禁止大量永久旧包 shim 混入根目录。

## 3. 先做真实基线审计

请从实际文件而不是凭记忆推断当前仓库结构。执行并保留：

- Git 当前分支、HEAD、`git status --short`；
- `git ls-files` 顶层文件清单、原入口、所有 Python 导入关系；
- 当前单元测试数量及可重现结果，必要的 SITL/Gazebo 检测；
- Python/ROS2/Gazebo/SITL 版本、可用环境、相关启动命令与配置位置；
- `legacy/` 是否被代码、测试、脚本、CI、文档运行命令引用；
- Git 跟踪与未跟踪数据、许可证、原生 C++ 构建、ROS 进程脚本、资源路径。

创建独立 `refactor/seven-module-layout` 或类似迁移分支，并分阶段提交。**保留用户现有未提交修改**：如遇冲突，不得 reset/clean/stash 丢弃数据；先采取安全隔离/局部提交策略，实在无法保障数据时报告明确阻塞，不要伪称完成。

## 4. 按职责迁移，不做机械目录重命名

参考新规范中的完整映射表，并特别检查以下容易错位的文件：

- `core/mission_runtime.py` → `engine/mission/`；`core/action_registry.py` → `engine/action/`；`core/vehicle_execution.py`、`vehicle_safety.py`、`control_authority.py` → `engine/control/`；`core/sitl_mode_action.py` 不应遗留通用 Engine 中。
- `actions/` → 新 `actions/`，按 common/rover/copter/navigation 等归属。当前并无 Plane 实现，不要创建假的 Plane 插件。
- `vehicles/`、`protocols/mavlink/`、车辆 TCP/serial transport → `vehicles/` 的 ArduPilot 共享模块与车型子包；避免 Rover 继续依赖 Copter 私有类作为长期结构，但本轮只能**等价提取和重定向**共享实现，不得改动指令行为。
- `sensors/`、`perception/`、`localization/`、`mapping/`、`world_model/`、`environments/` → 新 `world/`，保留发布/来源/版本/时间合同。
- `planning/`、`guidance/`、`intelligence/` → `autonomy/`。
- `integrations/ros2/nav2_*` → 依据调用目的归 `actions/navigation/` 或 `autonomy/planning/`；`integrations/ros2/rs16_scan.py` 和持续地图 ROS 进程 → `world/` 内对应领域；`integrations/robosense/` → `world/sensors/lidar/` 内所属 SDK；必须保留 native 文件、许可证和 notices。
- `application/`、`applications/`、`deployment/`、原 `app/` 与 `web_ui/` → 按用例、任务编排、装配、UI、导航业务职责分别归 `app/`、`actions/`、`autonomy/`、`engine/`，不得把巨大的 `deployment/application_runtime.py` 简单换个名字后引入不必要的功能重写；等价搬迁是主原则。
- `runtime/` 的 Python 装配逻辑移入 `app/bootstrap/`，TOML/JSON 配置按归属整理到 `configs/` 或 `simulation/profiles/`；原 `config/` 收敛为 `configs/`。
- 只有空占位的 `gateway/` 等删除，不创建新空占位。

**导入与依赖：** 全部 Python 包改为 `vehicle_autonomy.*` 正式路径；修复循环依赖、相对路径、动态导入、字符串模块名、`python -m ...`、`PYTHONPATH`、`__file__` 文件定位、资源文件访问。所有 `src/`、configs、SDF、rosbag、native 目录的定位在脚本和测试中可重现。ROS2/PyMAVLink/Gazebo 等可选依赖不能让纯合同/Core 的导入失败。

现有 shell 脚本、systemd 示例、GitHub Actions、测试 harness、ROS2 worker 子进程命令、CLI 与 Web 资源路径都应更新。对任何不可避免的 CLI 路径变化，提供明确的新命令和最小必要兼容说明。不得为了保留旧 `python -m app.main` 而永久保留整个旧根包。

## 5. Legacy 删除规则（本次必做）

1. 在任何删除前确认 `legacy/` 是**当前仓库内**的目录，绝不通过相似名字猜测并删除其他项目。
2. 记录 `git status --short -- legacy/`、`git ls-files legacy/`，检查其内的未跟踪文件是否存在重要本地数据或用户配置；如存在，先在非 `legacy/` 的安全目录留存，记录去向，不能盲目 `rm -rf`。
3. 将现行代码、测试、部署、CI 对 `legacy/` 的依赖全部解除；旧文档中的历史描述可以保留，但旧路径不可作为当前可执行指令。
4. 对 Git 跟踪内容用可审计的 Git 删除方式移除，再确认工作目录下 `legacy/` 不再存在。
5. 删除 Legacy 不等于移植 Legacy 内的旧业务，不要借这一步重引入 CUADC 旧架构。

## 6. 验证门槛

逐阶段运行并修复：

- 新包在受控 Python 环境中可以安装与完整导入，`python -m compileall`、测试发现与基本静态检查正常；
- `contracts/engine` 导入不需要已安装 ROS 2 或连接飞控；
- 原有核心单元、MAVLink 编解码、ControlAuthority、Safety、Stop、Mission、Web/API 等测试迁移后仍通过；
- 验证 read-only 硬件入口绝不发送运动命令，`hardware_controlled` 仍被明确拒绝；
- 可用时运行原 Copter/Rover SITL+Gazebo 全部可重现基础回归及故障场景，不能将历史 PASS 当本次 PASS；
- ROS2/RS16/ARM64 相关功能必须至少通过可运行的相关静态/离线/模拟测试；不在当前硬件环境能跑的测试记录明确原因，不能擅自标 PASS；
- 原有已知失败（例如历史 P26 统一导航门槛）必须如实保留，不许扩大豁免或借目录迁移声称已修复。

做完后全面搜索仓库，确保除了迁移报告、历史描述或明确说明外，没有执行中的旧导入路径、失效的 `python -m` 命令、硬编码旧运行资源路径和无意的 `legacy/` 依赖。

## 7. 输出与提交

所有工作直接在仓库内完成。输出：

- `docs/ARCHITECTURE_MIGRATION_REPORT.md`，包含**迁移前后目录结构、旧→新主要文件表、修改入口清单、运行与测试命令及输出摘要、失败与未执行原因、保留已知问题、删除 Legacy 的依据、Git 版本信息和后续建议**；
- README / AGENTS / 运行脚本 / CI 中必要的路径与安装说明同步修改；
- 若使用 `pyproject.toml`，提供最小可复现安装/测试入口，避免对现有 Python 3.10 ARM64 环境无意义地抬高版本要求或引入非必要新依赖；
- 对主要迁移阶段做有意义的 Git 提交，并在最终总结中给出 commit hashes、`git status --short`、测试 PASS/FAIL/BLOCKED 汇总及迁移未完成项。

完成时应满足：仓库有唯一的七模块源码布局、`legacy/` 已删除、现有支持能力和安全边界无行为回退，后续可以在新结构中继续开发新功能。

**请现在开始实际执行，不要停留在审计计划、空目录创建或提示词设计阶段。**
