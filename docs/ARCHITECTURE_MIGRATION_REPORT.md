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
- Copter/Rover 正常及故障物理基线正在独立自有进程中运行，后续补充结果。

## Legacy 删除前保护

当前运行代码 AST 导入和测试未发现对 Legacy 的依赖。引用主要是历史文档和旧路径排除规则。
仓库内 `legacy/` 实路径已核对，无符号链接；548 个跟踪文件，无普通未跟踪文件；923 个被忽略文件，包含缓存和 `legacy/cuadc_2026/runtime/eeprom.bin`（16384 字节）。

完整树已先备份到 `/home/level6/vehicle-autonomy-migration-backups/6df9fe9-legacy/legacy-complete.tar.gz`；同目录 `local-data-manifest.json` 记录每个本地文件的 SHA256 和大小。后续删除仅针对本仓库 Legacy，其他旧工程不动。

## 分阶段进度

1. 基线审计与保护：完成；物理基线待结束。
2. 按职责迁移、安装和入口修复：进行中。
3. Legacy 审计删除、回归与最终提交：待执行。

原始详细审计与日志保留在本地 `artifacts/migration/`；最终报告将补充迁移清单、提交和验证结果。
