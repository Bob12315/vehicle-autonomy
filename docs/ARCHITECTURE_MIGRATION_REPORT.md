# 七模块架构迁移报告

日期：2026-10-23（Asia/Ulaanbaatar）。范围：只迁移现有源码、入口与资源，不开发新能力、不连接实机控制。

## 迁移前审计

- 原分支 `main`，HEAD `6df9fe91819f430c7a0d8f153ff2b06b86895915`。
- 已跟踪工作树干净；用户提供的三份规范为未跟踪文件，原样保留并纳入版本控制。
- 工作分支 `refactor/seven-module-layout`。
- Python 3.12.3；Gazebo Sim 8.15.0；pymavlink 2.4.49；pyserial 3.5。
- Copter/Rover SITL、Gazebo 插件及依赖存在；隔离实例预检 PASS。ROS 2 位于用户隔离 Jazzy 环境，而非 `/opt/ros`。
- 迁移前 `python -m unittest discover -s tests -v`：340 tests，0 failures/errors/skips，31.629 s。
- 从 `legacy/cuadc_2026/` 运行历史 P0 合同/安全/执行精选基线：138 passed，1.18 s；不是整个 Legacy 测试集。
- `python scripts/preflight_simulation.py --isolated` 原来需要 `PYTHONPATH=.`；补充环境后 PASS。迁移将明确安装要求。
- Copter/Rover 完整正常场景与各自物理故障矩阵：4/4 PASS，均释放端口并清理自有进程组。

## Legacy 删除前保护

当前运行代码 AST 导入和测试未发现对 Legacy 的依赖。引用主要是历史文档和旧路径排除规则。
仓库内 `legacy/` 实路径已核对，无符号链接；548 个跟踪文件，无普通未跟踪文件；923 个被忽略文件，包含缓存和 `legacy/cuadc_2026/runtime/eeprom.bin`（16384 字节）。

完整树已先备份到 `/home/level6/vehicle-autonomy-migration-backups/6df9fe9-legacy/legacy-complete.tar.gz`；同目录 `local-data-manifest.json` 记录每个本地文件的 SHA256 和大小。后续删除仅针对本仓库 Legacy，其他旧工程不动。

## 分阶段进度

1. 基线审计与保护：完成，含物理基线。
2. 按职责迁移、安装和入口修复：179 个文件已移动、13 个空占位删除；原有 340 tests 全通过（31.612 s），compileall PASS。
3. Legacy 审计删除：548 个跟踪文件已用 git rm 删除，残留本地数据已额外保存，目录不再存在；回归进行中。

原始详细审计与日志保留在本地 `artifacts/migration/`；最终报告将补充迁移清单、提交和验证结果。

## 源码迁移阶段检查

逐文件清单见 [architecture_migration_files.json](architecture_migration_files.json)。
关键合同、原 core、Action、Vehicle 和 MAVLink 共 63 个文件去除 import/docstring 后 AST 与原 HEAD 一致。
原生 C++ 和 License/Notice 字节 SHA256 与迁移前完全相同。
`application`、`deployment` 已按数据、算法、场景、任务设计、入口和装配拆分；
Rover 不再从 Copter 私有包导入共享 writer/session/telemetry/translator。
安全依赖扫描更新为新路径并保留原检查范围，防止扫描空目录得到假 PASS。

临时副本测试曾发现 18 个 SITL 测试仍引用分段拼接的旧配置路径，已修复路径而未改断言。
隔离 venv 复用迁移前解释器的已安装依赖（显式 `.pth`），通过 editable install 验证源码。
普通无依赖 wheel 的默认 status、hardware --check 和 41 个合同/Engine 子模块导入通过；
具体 MAVLink 运行包仍按原条件要求可选 pymavlink，并未提升为基础合同依赖。

## 删除记录

完整跟踪文件及 SHA256、备份 SHA256、本地数据摘要见
[Legacy 删除清单](architecture_migration_legacy_deletion.json)。删除前再次确认 Git
工作树无 Legacy 修改、无普通未跟踪文件，tar 备份中 eeprom 内容与本地一致。
`git rm -r legacy` 删除 548 个跟踪文件；余下忽略文件（包括运行历史测试产生的缓存）
移至备份目录的 `legacy-residual-after-tests/`，无数据盲删。原顶层包中的缓存和其他
忽略数据保存在 `/home/level6/vehicle-autonomy-migration-backups/6df9fe9-root-local/`。
仅操作当前仓库的 Legacy；未操作外部历史项目。历史文档已明确标记为历史记录。

新增迁移检查覆盖唯一源码布局、所有迁移模块导入、仓库外 cwd 的默认安全入口与
原有 hardware_controlled 明确拒绝信息。第一次检查预期错误文本不匹配，修正为
原实现的 `hardware control is unimplemented; onsite independent safety acceptance required`，
未改变实现或原有断言。

Legacy 删除后 `python -m unittest discover -s tests -v`：342 tests，0 failures/errors/skips，31.767 s。
所有 Shell 入口 `bash -n` PASS；279 个 Python 文件按 Python 3.10 语法解析 PASS。
本机无 Python 3.10/ARM64 解释器，实际该平台运行尚未重测；CI 已增加 3.10/3.12 安装测试矩阵。
普通 wheel 检查还修正了嵌套在仓库内的 venv 误选源码资源的问题：仅实际 `src/vehicle_autonomy`
布局使用源码资源，安装包使用其自身 `sys.prefix/share/vehicle-autonomy`。

阶段提交：`78d86fb` 审计与保护，`3cb42d9` 七模块迁移。后续提交与物理回归结果待补充。
