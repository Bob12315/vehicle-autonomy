# Mission、Action 与 Capability

**状态：Frozen Target Architecture。** 当前 Action Mission 实现见[当前状态](../migration/current_state.md)。

## Action

Action 是自主系统预先实现、测试、注册的原子能力 API。每项能力必须定义参数 Schema、输入、输出、生命周期和 Safety 约束。示例名包括 `takeoff`、`land`、`goto`、`stop`、`observe`、`search`、`orbit`、`follow`、`payload_release`；名称示例不代表每辆车支持。Action Registry 提供可查询的能力定义及实现绑定，不能让 AI 在运行时生成新的底层控制能力。

VehicleCapabilities 决定某个 Vehicle Plugin 可执行的能力。例如 `can_takeoff`、`can_land`、`can_hover`、`can_reverse`、`position_control`、`velocity_control`、`heading_control`、`supports_payload`、`supports_gimbal`、`supports_loiter`。Mission、Action Registry、Web 与未来 Mission Compiler 可据此判断合法性。Rover 上包含 `takeoff` 的 Mission 应在开始前因 capability mismatch 被拒绝，而非运行到发送阶段才尝试。

## Mission

Mission 只管理 Action 顺序、参数引用、条件、retry、branch、failure policy 和 mission lifecycle。Mission 不含 MAVLink、PWM、串口、UDP、驱动或轨迹控制。具体路线计算交给 Planning，当前运动目标交给 Guidance；Action 可调用这些 Contract，最终仍须产生受控 Effect。

```text
human config / Web UI / LLM planner / rule planner / external system
                              │
                              ▼
                       MissionProposal
                              │
                              ▼
                 Mission Validation / Compile
               schema + action registry + capability
                              │
                              ▼
                       Validated Mission
                              │
                              ▼
                        Mission Runtime
                              │
                              ▼
                        Registered Action
```

Mission Runtime 不关心 Proposal 的生产者。LLM 未来只能是 Mission Producer，不承担 Runtime 权限。验证还应检查参数、依赖、环境前置条件及安全约束；具体算法和 Schema 留待后续设计。[Execution / Safety](execution_safety.md)定义 Action 后的唯一副作用出口。[Intelligence 边界](../intelligence/boundaries.md)定义 AI 权限。
