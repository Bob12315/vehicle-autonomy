# P11 Intelligence 预留边界

**状态：只预留目录，不实施 Intelligence。** 新建 `contracts/intelligence/` 和 `intelligence/` 的包入口，不导出接口，不注册服务，也不接入当前生产运行链。LLM、VLM、Laya、Agent、Mission Planner 及模型/算法均留待单独的 Intelligence Architecture V1 设计。

未来 Intelligence 的输出边界是 `Intent`、`MissionProposal`、`SemanticObservation` 或 `PolicyDecision`。任何提案仍须经过 Mission validation、已注册 Action、Execution、Authorization 和 Safety，才能到达车辆。Intelligence 永久不得直接持有 `VehicleCommandPort` 或访问 Protocol、Transport 与硬件 writer；现有架构校验脚本对新增 Intelligence 包施加静态导入限制。

本轮验证包可导入、架构边界及 Stable Core 校验通过、当前 SEND 默认关闭。全量回归为 `766 passed, 3 failed`；三项失败与 P9 基线相同，涉及 `rk3588-real` Profile 行数、`align_descend` 行数和 `goto_waypoint` 完成状态断言。本轮没有声称已具备 AI Mission Producer 或真实车辆控制能力。
