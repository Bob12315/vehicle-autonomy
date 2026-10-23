# 七模块文件架构迁移报告

日期：2026-10-23（Asia/Ulaanbaatar）。范围：文件组织、imports、安装、入口、资源、测试与 CI；没有新增业务能力或开启实机控制。

## 结论

源码已收敛到唯一 `src/vehicle_autonomy/` 七模块布局，仓库内 Legacy 已删除并保护本地数据。
原有 340 项 Python 测试迁移后全部通过；加入 2 项迁移检查后 342 项通过，0 跳过。
双车物理回归存在迁移前同样可复现的启动/真值观测失败，**不能宣称完整仿真套件 PASS**。
实际结果与未执行范围见下文及[结构化验证记录](architecture_migration_validation.json)。

## 审计与版本

- 原分支 `main`，HEAD `6df9fe91819f430c7a0d8f153ff2b06b86895915`。
- 初始跟踪文件无未提交修改；三份用户迁移规范未跟踪，已原样纳入版本控制。两个权威架构规范及迁移提示文件内容均未改写。
- 独立分支 `refactor/seven-module-layout`；未 push。
- Python 3.12.3；Gazebo Sim 8.15.0；pymavlink 2.4.49；pyserial 3.5；隔离 Jazzy/SLAM Toolbox 2.8.5、Nav2 1.3.13 可用。
- 旧入口、完整跟踪清单、AST 导入、资源定位及本地文件清单在 `artifacts/migration/`；版本与基线摘要已提交到 [baseline JSON](architecture_migration_baseline.json)。

## 前后布局与逐文件归属

迁移前正式代码散布于 `core`、`application`、`applications`、`deployment`、`runtime`、`integrations` 等根包。
迁移后：

```text
src/vehicle_autonomy/
  contracts/                 稳定类型与端口合同
  engine/{action,mission,control}/
  actions/{common,rover,navigation,devices,composite}/
  vehicles/{ardupilot,copter,rover}/
  world/{model,sensors,perception,localization,mapping,environment,transform}/
  autonomy/{planning,guidance,intelligence}/
  app/{api,operator,mission_designer,scenarios,web,bootstrap}/
configs/  simulation/  tests/  scripts/  docs/  .github/
pyproject.toml
```

179 个跟踪文件迁移（其中 158 个 Python 文件），13 个旧空占位/包壳删除；新包共有 182 个 Python 文件。
没有遗留旧根包或永久 shim，没有空 Plane 实现或新的全局 adapters/integrations 包。
完整清单见[旧→新文件映射](architecture_migration_files.json)。主要归属如下；表中新路径均相对 `src/vehicle_autonomy/`：

| 原归属 | 新归属/说明 |
| --- | --- |
| `contracts/` | `contracts/`，冻结合同不拆碎 |
| `core/actions.py`、`action_registry.py` | `engine/action/runtime.py`、`registry.py` |
| `core/mission*.py` | `engine/mission/compiler.py`、`runtime.py` |
| `core/*execution.py`、`control_authority.py`、`vehicle_safety.py` | `engine/control/` |
| `core/sitl_mode_action.py` | `actions/common/sitl_mode.py`，具体行为离开 Engine |
| `core/transform.py` | `world/transform/tree.py` |
| 原 `actions/` | common/basic、rover/maneuver、navigation/path_following |
| `applications/cuadc/actions.py`、仿真 payload port | `actions/composite/cuadc.py`、`actions/devices/simulation_payload.py` |
| `vehicles/multirotor` 共享会话、writer、遥测基类、translator | `vehicles/ardupilot/`；Rover 不再依赖 Copter 私有包，原默认 Copter/subclass 行为保留 |
| 车型诊断、SITL guard；`vehicles/rover/` | `vehicles/copter/`；`vehicles/rover/` |
| MAVLink 协议、车辆字节传输 | `vehicles/ardupilot/mavlink/`、`transports/` |
| 传感器、感知、定位、地图、环境、WorldModel | `world/` 对应所有者；OfflineStateChain 也归 World |
| `planning`、`guidance`、`intelligence` | `autonomy/` 对应算法包 |
| Nav2 planner/worker、只读 PlanningService | `autonomy/planning/`；无车辆控制端口 |
| ROS mapping/RS16 topic 节点、SDK C++ | `world/mapping/`、`world/sensors/lidar/`；不强制成为 Action |
| 原生 SLAM overlay 源码、许可证和 notices | `world/mapping/native/`，字节 SHA256 不变 |
| `application` 人工审批/任务设计/API | `app/operator`、`mission_designer`、`api`；导航目标类型归算法域 |
| `applications` 场景、目标和业务配方 | `app/scenarios/`，可复用 CUADC 行为单独归 Action |
| `deployment` 装配 | `app/bootstrap/`；导航算法/作业归 autonomy，仿真 Safety 归 engine |
| `deployment` 场景/扫描 rejection-only guards | `autonomy/guidance/`，不把业务算法塞入通用 Engine |
| Web/静态文件 | `app/web/` 和 `app/web/static/` |
| Python runtime profile/配置解析 | `app/bootstrap/`；原 TOML → 根 `configs/sitl*.toml` |
| 原 `config/` | 根 `configs/`；实际外置安装配置目录保持原位置 |

145/158 个迁移 Python 文件去掉 imports/docstrings 后 AST 完全一致；其余 13 个差异已核对为模块字符串、默认配置、资源定位或子进程路径。
其中合同、原 core、Action、Vehicle、MAVLink 的 63 个关键文件 AST 全部一致。
489 条内部导入已审计，旧顶层包导入泄漏为 0。没有修改 SEND、Lease、TTL、Frame/版本/来源、唯一 writer、停止确认或运动限值。

## 入口、资源和兼容变化

| 原入口 | 新模块入口 / 安装命令 |
| --- | --- |
| `python -m app.main` | `python -m vehicle_autonomy.app.cli` / `vehicle-autonomy` / `python -m vehicle_autonomy` |
| `python -m app.hardware` | `python -m vehicle_autonomy.app.bootstrap.hardware` / `vehicle-autonomy-hardware` |
| `python -m app.web` | `python -m vehicle_autonomy.app.web.cli`（或 `vehicle_autonomy.app.web`）/ `vehicle-autonomy-web` |
| `python -m app.plan` | `python -m vehicle_autonomy.app.planning` / `vehicle-autonomy-plan` |
| `python -m app.anchor` | `python -m vehicle_autonomy.app.anchor` / `vehicle-autonomy-anchor` |
| `python -m deployment.onboard` | `python -m vehicle_autonomy.app.bootstrap.onboard` / `vehicle-autonomy-onboard` |
| `integrations.ros2.run` | `vehicle_autonomy.app.bootstrap.ros2_run` |
| ROS mapping、Nav2 worker、RS16 scan | `world.mapping.ros2_node`、`autonomy.planning.nav2_worker`、`world.sensors.lidar.rs16_scan`（均加 `vehicle_autonomy.` 前缀） |

README、AGENTS、运行文档、Shell/Python/JS harness、systemd 样例和 CI 已同步。
CI 安装新包，运行 3.10/3.12 矩阵、Python 测试、JS 行为检查及安全默认入口；此处不冒充已执行远端 CI。

`_resources.resource_root()` 只在真实 src 布局选择源码资源；普通 wheel 使用本安装 prefix 的 `share/vehicle-autonomy`。
可显式提供 `VAF_RESOURCE_ROOT`，无效资源集明确报错。用户传入的相对路径仍相对调用目录。
ROS worker 的源码指纹从实际安装模块读取，静态 UI/native/license/service 文件包含在 wheel 内。
源码 preflight 显式加入本仓库 tests 路径，解决旧脚本直接运行时的导入失败。
外置 `$VAF_INSTALL_ROOT/config/` 是用户跨版本配置，保留其原有位置；它不是已移除的仓库 `config/`。
部署脚本仍只生成归档/安装并执行 readonly 检查，不启用自启动；本轮未实际向远端部署。离线 wheelhouse 需包含 setuptools>=61、wheel 及其全部依赖，部署器显式安装这些构建工具；全新无依赖 venv 的离线源包构建/安装及 readonly --check 已通过（首次 wheelhouse 漏 packaging，补齐后通过）。

## 测试命令与结果

可复现安装与基础检查：

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -e '.[mavlink]' -r requirements-vision.txt
python -m compileall -q src tests scripts
python -m unittest discover -s tests -v
vehicle-autonomy status
vehicle-autonomy-hardware --check
node tests/web_console_smoke.cjs
```

本轮测试 venv 显式以 `.pth` 复用迁移前依赖，避免替换宿主包；另有不安装 ROS/PyMAVLink 的独立 wheel venv。

| 检查 | 实测结果 |
| --- | --- |
| 迁移前新框架单元测试 | 340 PASS，0 失败/错误/跳过，31.629 s |
| 迁移前 Legacy P0 精选合同/安全/执行测试（从旧树内运行） | 138 PASS，1.18 s；不是整个 Legacy 测试集 |
| 迁移前 Copter/Rover 完整物理场景及两车故障矩阵 | 4/4 PASS，进程组和端口清理通过 |
| 迁移后原测试 / Legacy 删除后测试 | 340 PASS（31.612 s）/ 342 PASS（31.767 s）；套件内另一次 342 PASS（31.952 s） |
| compileall / Shell bash -n / Python 3.10 语法解析 | PASS / PASS / 279 文件 PASS；语法解析不等于真实 3.10 运行 |
| editable install / 普通 wheel 安装 | PASS；最小 wheel 从 `/tmp` 使用安装资源，41 个 contracts/engine 子模块无需 ROS/PyMAVLink 即可导入 |
| 安全默认入口 | status 无连接/SEND=false；hardware --check 双 SEND=false；hardware_controlled 以原明确错误拒绝 |
| Web Python/API 测试及 JS 行为检查 | 原 Python 测试 PASS；原 JS 的 11 检查 PASS（连接的 Node REPL CommonJS/VM，宿主 PATH 无 node）；不代表视觉 QA |
| 原生 SLAM overlay | 构建 PASS；上游 dropped_endpoints=2，显式修复 overlay=0，原 ABI/版本 pin 保留 |
| 官方 RS16 adapter | 固定 SDK revision 的 PC C++ 编译 PASS；复制原 SDK license；未启用可选 libpcap |
| RS16 ROS 合成链 | Jazzy 自测试 PASS，accepted=6、rejected=2；不是实物或 PCAP 证据 |
| Nav2 原只读回归 | PASS：绕墙、拒绝无路径/未知/窄门、旋转原点、记录地图、公开 CLI、实际 native timeout 和清理 |
| 安装 wheel 的 Nav2/ROS worker | PASS，使用安装资源和模块指纹；只读 executable=false。首次最小环境缺可选 PyYAML，显式补充原依赖后通过，未改源码 |
| 双车完整套件首轮 | FAIL：前 4 场景 PASS，第 5 个 Copter Action 启动 `physical oracle stale`，原 fail-fast 留下 16 项未执行 |
| 原 HEAD 对照 | 相同 Copter Action 及 basic_route（2 repeats）、相同二进制/插件均复现相同 stale 错误；临时参考 clone `/tmp/vaf-migration-reference`，无修改外部历史项目 |
| 原剩余场景续跑 | 21 项全部执行：19 PASS、2 FAIL；0 未执行，全部失败保留 |

完整套件命令：

```bash
PATH="$PWD/.venv-migration/bin:$PATH" ./scripts/test_simulation_v1.sh \
  --run-dir "$PWD/artifacts/migration/sim" \
  --build-dir "$PWD/artifacts/simulation/build"
```

其他本轮实际命令（需激活测试 venv；重跑时为输出目录选择新名称）：

```bash
./scripts/with_ros2.sh python -m vehicle_autonomy.world.mapping.build_slam_boundary \
  --output-dir "$PWD/artifacts/migration/native-boundary"
./scripts/with_ros2.sh python -m vehicle_autonomy.world.sensors.lidar.rs16_scan \
  --config configs/rs16-scan.json --health-file artifacts/migration/rs16-health.json --self-test
./scripts/build_rs16_adapter.sh "$PWD/artifacts/hardware-ready/rs_driver" \
  "$PWD/artifacts/migration/rs16-native"
python -m tests.simulation.nav2_planning --run-dir "$PWD/artifacts/migration/nav2"
python -m pip wheel --no-deps --no-build-isolation . -w artifacts/migration/wheels
```

Legacy 精选 138 项采用 [P0 基线中的完整历史 pytest 命令](migration/p0_baseline.md)，
本轮在删除前从 `legacy/cuadc_2026/` 执行，输出 `138 passed in 1.18s`。
该历史命令不能直接用于已删除归档的当前 checkout；如需复核，使用 Git `6df9fe9` 的独立参考副本。

原始首轮失败不覆盖。续跑按原 `harness.py` 的场景表、360 秒每场景期限、原断言及相同清理判据，独立保留于 `artifacts/migration/cont/`。
完整场景状态：

| 场景 | 状态 | 说明 |
| --- | --- | --- |
| copter_application | PASS | 进程组/端口清理通过 |
| rover_application | PASS | 进程组/端口清理通过 |
| copter_environment | PASS | 进程组/端口清理通过 |
| rover_environment | PASS | 进程组/端口清理通过 |
| copter_actions | FAIL | RuntimeError: physical oracle stale |
| rover_actions | PASS | 进程组/端口清理通过 |
| copter_route | FAIL | RuntimeError: physical oracle stale |
| rover_route | PASS | 进程组/端口清理通过 |
| copter_mission_faults | PASS | 进程组/端口清理通过 |
| rover_mission_faults | PASS | 进程组/端口清理通过 |
| objects | PASS | 进程组/端口清理通过 |
| cuadc_first | PASS | 进程组/端口清理通过 |
| cuadc_second | PASS | 进程组/端口清理通过 |
| rover_inspection | PASS | 进程组/端口清理通过 |
| business_faults | PASS | 进程组/端口清理通过 |
| visual_business | PASS | 进程组/端口清理通过 |
| copter_full | PASS | 进程组/端口清理通过 |
| copter_land | PASS | 进程组/端口清理通过 |
| rover_full | PASS | 进程组/端口清理通过 |
| copter_faults | PASS | 进程组/端口清理通过 |
| rover_faults | PASS | 进程组/端口清理通过 |

## 失败、限制与未执行项

- 初次临时迁移检查发现 18 项 SITL 测试的分段旧配置路径，已修正路径，原断言不变；正式 340/342 项均通过。
- 新增安全检查最初期望了不同错误文字，已对齐原实现的明确拒绝信息，没有改实现或放宽条件。
- 物理 oracle 启动失败及后续具体失败详见场景表和结构化证据；没有删除测试、增大时效容差、改变运动阈值或将已有失败标 PASS。
- 历史 P26 统一导航越轨/定位新鲜度 FAIL、长运行资格与原生启动问题原样保留。本次不重新宣称 P26、实车、服务器、RKNN、Plane 或新导航能力通过。
- 本机无 Python 3.10/ARM64 板卡运行环境；未远端部署/运行 ARM64，未重测真实 Camera/RS16/飞控，也没有发送实机命令。
- 未执行实际 PCAP 回放、外部服务器 LLM 的八场景实践套件及完整 P26 endurance；不以先前历史 PASS 替代本轮验证。
- 实际 hardware_controlled 仍拒绝。硬件写入、定位资格、动态避障和物理制动仍需独立验收，不属于本次文件迁移。

## Legacy 删除和本地数据保护

仅核查并移除 `/home/level6/vehicle-autonomy-framework/legacy/`，核对其非符号链接且实路径匹配。
现行源码 AST、测试、脚本、CI 不依赖 Legacy；历史文档已标注为历史，失效的 Legacy 导航链接已改为 Git 历史说明。

- 548 个跟踪文件，初始无跟踪修改、无普通未跟踪文件。
- 923 个被忽略的本地文件，含缓存及 `runtime/eeprom.bin`（16384 字节）。
- 删除前完整备份：`/home/level6/vehicle-autonomy-migration-backups/6df9fe9-legacy/legacy-complete.tar.gz`。
- 同目录 `local-data-manifest.json` 记录本地文件大小/SHA256；删除前比对本地和 tar 内 eeprom 内容一致。
- 对跟踪内容使用 `git rm -r legacy`。余下忽略内容（包括历史测试产生的缓存）移至同备份目录 `legacy-residual-after-tests/`，未盲删本地数据。
- 原根包 182 个 bytecode 缓存文件额外保护在 `/home/level6/vehicle-autonomy-migration-backups/6df9fe9-root-local/`，含 manifest；未搬回运行包。
- 完整删除清单、跟踪文件 SHA256 和 tar 备份 SHA256 见 [Legacy 删除记录](architecture_migration_legacy_deletion.json)。
- 最终工作目录无 Legacy，`git ls-files legacy/` 为空；其他独立历史工程未修改、未删除。历史源码仍在 Git `6df9fe9`。

## 提交与最终状态

- `78d86fb` docs: record migration baseline and protect local legacy data
- `3cb42d9` refactor: migrate runtime into installable seven-module package
- `2e90a49` refactor: remove audited legacy tree and verify isolated package layout
- `e0c2ca9` fix: resolve source preflight and document installed resource checks
- `875e802` fix: migrate JavaScript smoke resource path and preserve regression evidence
- `8b2893a` fix: provision isolated build tools for offline source deployment

最终报告提交主题为 `docs: finalize architecture migration results and retained failures`。
交付前复核 `git status --short` 为空；所有自有测试进程组结束、端口释放，Legacy 不存在。
本地原始日志和备份保留；Git 仅提交正式源码、配置、测试与审计证据。

后续工作应从新七模块路径继续。物理仿真已有故障、P26 与硬件资格单列跟进，不在本次迁移中改动其安全条件或新增能力。

## 后续文档清理（2026-10-23）

按用户要求移除已被取代的规划/提示词/进度/候选清单；源码、配置、测试、第三方许可证不变。
两份根目录权威架构规范、冻结合同、运行指南、独立阶段审计、P26 FAIL/硬件限制和迁移证据保留。
早期 `migration_plan.md` 和 P0 baseline 含独立台架/安全/测试记录，继续保留。
已更新 README 和其余 Markdown 引用；必要的历史来源使用 `git show bf4ea1f:<path>` 查阅。
删除清单如下，文件完整版本仍在 Git `bf4ea1f`：

| 文件 | 删除依据 |
| --- | --- |
| `Codex_Architecture_Migration_Prompt.md` | 迁移任务已完成，结论与验证已记录在迁移报告 |
| `SIMULATION_COMPLETION_PLAN.md` | 已完成的 Phase 0–8 实施计划，保留对应完成审计和阶段证据 |
| `docs/framework_v1.md` | 旧版目标架构，由根目录 V1.0 系统规范与 V1.1 文件规范取代 |
| `docs/v1_progress.md` | 旧百分比进度表和失效源码链接，由实现边界与实际验收审计取代 |
| `docs/basic_autonomy_implementation_plan.md` | P9–P17 已完成的实施计划，保留完成审计 |
| `docs/p6_runtime_integration_plan.md` | P6 已完成的实施计划，历史内容可从 Git 查看 |
| `docs/p9_application_runtime_plan.md` | P9 已完成的实施计划，保留阶段审计与当前实现边界 |
| `docs/migration.md` | Legacy 简介，与现有迁移报告重复 |
| `docs/migration/p0_inventory.md` | 已删除 Legacy 的旧候选清单，保留原 P0 基线和测试记录 |
| `docs/autonomy/cuadc_candidate_inventory.md` | 已完成的 Legacy 候选审查，保留业务验收审计 |
| `docs/autonomy_roadmap.md` | 旧 P21–P25 实施路线图，保留完成审计和未通过的 P26 门槛 |

本次清理验证：`.venv-migration/bin/python -m unittest discover -s tests -v`，
342 项通过，0 失败/错误/跳过（31.759 s）；保留 Markdown 本地链接检查 0 失效，
`git diff --check` 通过。变更仅限 Markdown，因此未重复执行物理仿真；此前 19/21
及两项既有 oracle 失败、P26 FAIL 的记录不变。
