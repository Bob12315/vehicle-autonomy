# Intelligence 权限边界

**状态：Frozen Target Architecture。** 只冻结权限边界；LLM、VLM、Policy、Agent、mission_planner 的具体模型、Laya 集成与规划算法以后设计。

Intelligence 可读取 WorldSnapshot，并产出 `SemanticObservation`、`Intent`、`MissionProposal` 或 `PolicyDecision`。MissionProposal 经过 validation / compile，形成 Validated Mission 后才由 Mission Runtime 执行；Intelligence 本身既不成为 Mission Runtime，也不创建未注册 Action。

```text
WorldSnapshot → LLM / VLM / Policy / Agent
                           │
                           ▼
                Intent / MissionProposal
                           │
                           ▼
                 Validation → Mission / Action
                           │
                           ▼
                  Execution → Safety → Vehicle
```

Intelligence 永远不能直接获得 `VehicleCommandPort`、MAVLink、serial 或其他原始发送能力。`LLM → raw Vehicle Command`、`VLM → MAVLink`、`Agent → serial` 永久禁止。AI 建议也不能取消 Safety 的最终裁决权。当前源码中的感知能力不应被误称为已经实现 LLM / VLM / Agent。
