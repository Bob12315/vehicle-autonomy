# P10 Legacy Cleanup 门禁审计

**状态：审计完成；旧实现尚不满足删除条件。** P10 计划要求同时证明新 owner 已运行、消费者已切换、测试通过且兼容路径没有调用方，之后才能按 wrapper、adapter、目录、配置、导入、文档引用的顺序删除。当前只做框架边界审计，不改控制链或业务细节。

| 待清理层 | 当前调用或阻塞证据 | 结论 |
| --- | --- | --- |
| Legacy wrappers | `missions/common/actions/{takeoff,land,change_speed}.py` 仍被测试直接导入；`takeoff` 的旧模块时钟也仍被测试 patch。 | 旧导入消费者尚未全部切换。 |
| Old adapters | `missions/core/production_catalog.py` 仍创建 `LegacyActionModuleAdapter`；`application/vehicle_composition.py` 仍有集成测试消费者。 | 候选 Core 的 Action 注册仍依赖兼容层。 |
| Old directories / runtime | `app/main.py` 创建 `SystemRunner`；`application/runner.py` 创建 `ActionRuntimeService` 并触发旧 Mission 后台 tick。 | 候选 Core 尚未成为生产 Mission / Action owner。 |
| Deprecated config | 默认 `config/telemetry.yaml` 选择 v2 writer，`legacy_writer_enabled` 为 false；`telemetry_link/config.py`、`link_manager.py` 仍有受配置控制的旧 writer 分支和测试。 | 默认关闭不等于无调用方或可删除；保留唯一 writer 选择。 |
| Deprecated imports / docs | 旧导入仍供现有测试及兼容层使用；迁移文档中的旧路径用于说明实际债务。 | 随 owner 切换和消费者迁移逐项清理。 |

`python scripts/validate_stable_core.py --strict` 当前报告七项阻塞：五个旧文件仍在、production catalog 仍注册兼容 Action、旧 Mission 后台 tick owner 仍在。普通架构边界检查通过，只证明当前隔离规则，不代表已完成生产切换。`executor.send_commands: false`、系统 SEND 与 Action 双门控、唯一 writer、连续命令 stop/zero 和 stale 清理均保持原样。

下次删除前应先完成生产 owner 切换，逐项查找代码、测试、工具和配置消费者，运行相关及全量回归，再按计划顺序删除。P10 本轮没有删除仍在使用的路径，也不把离线候选 Core 测试视为生产接管证明。
