# P15 最小非车辆 Effect 合同扩展

现有 ActionDecision/ExitDecision/ActionSpec 仅允许 VehicleEffect，MissionRuntime 仅封装车辆 Envelope。仿真投放不属于车辆导航，也不能映射 Servo/PWM；这是 P15 的实际语义缺口。

增加 `ReleasePayloadEffect`、独立 `PayloadEffectEnvelope` 和 Execution-only `PayloadCommandPort`。新请求携带 payload、目标身份/producer/Observation、空间位置、capture 时间、Environment 版本；Envelope 保留 Run/Action/Effect/创建/截止身份。Action 的 allowlist 扩展为明确注册的车辆和载荷集合，Mission 按请求类别生成独立 Envelope。EffectResult 各阶段与停止/失败合同不变；旧 VehicleEffect、Vehicle Envelope 和 VehicleExecution 继续只接受车辆类型。

这是一项加法扩展，旧 Action、参数、Mission 与导入路径兼容。不提供真实载荷实现。Execution 必须有显式载荷 Safety，校验双 SEND、Action lease、generation/session/deadline、目标来源/新鲜度/Frame、对准/停止/库存；提交和最终 mutation 都复核。相同 Envelope 幂等；已释放 payload 不可再次释放；取消待提交请求，已经发生的副作用不能撤回。完成必须有后续独立载荷 Observation 与 WorldSnapshot，ACK 不代表完成。

合同测试：旧车辆 Envelope 拒绝载荷、参数和时间拒绝、Action allowlist、Mission 保留独立 Envelope 身份/期限、VehicleExecution 拒绝跨类型。实现与业务分开提交。
