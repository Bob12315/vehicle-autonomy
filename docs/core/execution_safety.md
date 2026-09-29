# Execution / Safety

**状态：Frozen Target Architecture。** 当前真实发送实现不同，见[当前状态](../migration/current_state.md)。

所有实际车辆运动必须通过唯一控制出口：

```text
Mission → Action → Planning / Guidance → Typed Effect / Command Intent
                                         ↓
                                     Execution
                                         ↓
                                   Authorization
                                         ↓
                                       Safety
                                         ↓
                                VehicleCommandPort
                                         ↓
                            Vehicle Plugin → Protocol
                                         ↓
                             Transport → Physical Vehicle
```

Execution 接收类型化 Effect、管理执行生命周期和派发；Authorization 检查操作者、运行上下文和发送许可；Safety 检查车辆状态、边界、时效、限幅及停止条件，拥有最终裁决权。Vehicle Plugin 把通过裁决的抽象命令翻译为车辆语义。任何新 Effect 类型都必须明确授权与 Safety 处理；缺少处理时拒绝执行。

`LLM → MAVLink`、`VLM → VehicleCommand`、`YOLO → Flight Controller`、`Mission → pymavlink`、`Planner → raw serial`、`Web button → raw servo` 都违反该链。不能为同一车辆建立第二条 writer 或备用直发路径。

对于连续运动，停止、取消、失效、断连和切换必须明确产生 stop/zero，并清除过期命令，避免重连后重放。跨 onboard、server、hybrid 部署仍需维持同等裁决；Gateway 的本地 watchdog 和 emergency fallback 不能成为绕开 Safety 的常规发送入口。当前 `executor.send_commands: false`、系统 SEND 与 Action 授权双门控必须在迁移期间保留，不因目标架构冻结而改变。
