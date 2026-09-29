# World Model

**状态：Frozen Target Architecture。** 本轮只冻结职责，不设计完整 WorldSnapshot Schema；现有 `fusion/` 等实现不自动等同于目标 World Model。

World Model 表示“系统当前认为现实世界是什么样子”。它接收 Sensor / Perception 的 Observation、Localization 的位姿与质量、Mapping 的空间表示、Vehicle 状态，以及 Environment 的静态或配置场景信息，发布带时效和质量信息的 `WorldSnapshot`。

未来快照可能包含车辆状态、pose、velocity、battery、health、objects、targets、obstacles、map、terrain、zones、semantic entities、environment state 与 mission relevant context。这里是信息范围，不是冻结的巨型字段表。

```text
Sensors → Perception / Localization / Mapping ─┐
Vehicle state ───────────────────────────────────┼→ World Model → WorldSnapshot
Environment ─────────────────────────────────────┘                      │
                                                  Intelligence / Mission / Planning
```

World Model 负责统一访问和状态表达，不直接连接原始硬件，不做 Mission 决策，不持有 VehicleCommandPort。上层优先读 WorldSnapshot；需要实时数据时也应通过明确 Contract，而不是私连传感器。失效与不确定状态应可见，不能把旧观测默认为当前事实。数据抽象见[数据流](../architecture/data_flow.md)。
