# V1 数据流

**状态：Frozen Target Architecture。** 本文冻结数据抽象与方向，不预设完整 Schema，也不声称当前所有类型已实现。

| 抽象 | 含义 | 典型来源与去向 |
| --- | --- | --- |
| Observation | 对传感器数据或感知结果的结构化观测，保留时间戳、frame 与质量信息 | Sensor / Perception → World Model |
| WorldSnapshot | 系统在某时刻对车辆和环境的统一状态理解 | World Model → Intelligence / Mission / Planning |
| Intent | 高层表达“想做什么”，如前往目标 A、检查物体 B、搜索区域 C | Operator / Intelligence → Mission proposal 或已注册 Action 的入口 |
| Effect | Action 请求的类型化副作用，如车辆运动、拍照、录制或载荷操作 | Action → Execution / Safety → 受控平台端口 |

```text
Sensor data ──→ Observation ──→ WorldSnapshot
                                      │
                                      ▼
                                    Intent
                                      │
                                      ▼
                        Mission Validation / Action
                                      │
                                      ▼
                               Typed Effect
                                      │
                                      ▼
                     Execution → Authorization → Safety
                                      │
                                      ▼
                              Vehicle / Platform
```

Localization、Mapping 和 Environment 也向 World Model 提供空间和场景信息。WorldSnapshot 应标明数据时效和质量；上层不能把失效观测当成持续有效状态。Intent 不具有发送权限；Effect 也不是直接的 wire message。实际车控还需要能力匹配、授权和最终安全裁决。参见[World Model](../core/world_model.md)、[Mission / Action](../core/mission_action.md)与[Execution / Safety](../core/execution_safety.md)。
