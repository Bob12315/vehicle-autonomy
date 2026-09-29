# 后续迁移原则

**状态：Migration Work 原则；本轮不实施代码迁移。** 冻结架构是目标，[当前状态](current_state.md)描述现状。具体迁移任务与顺序以后单独制定。

1. 不做 big-bang rewrite；一次只迁移一个清晰架构边界，并明确验收事实。
2. 保持相关测试通过；迁移前核对当前调用链、配置和实际行为，必要时补充能验证边界的测试。
3. 保留当前 Safety 行为：默认 SEND 关闭、双门控、stop/zero、过期命令清理、失效拒绝与 payload 受控路径。
4. 不引入重复控制链或并行 writer；任何切换都需证明唯一 owner 和回退条件。
5. 不同时重写 Mission、Vehicle 与 Transport；避免无法定位行为变化。
6. 新依赖遵守[依赖规则](../architecture/dependency_rules.md)。车辆差异通过 Plugin / Capability，硬件协议经 Vehicle / Protocol / Transport 分层。
7. 用 Current / Target 标签标识文档、接口和示例；只有经过实现与验证的能力才能写成当前支持。

本文件不包含旧 AR/PA/CF 任务编号、历史验收记录或具体迁移排期。
