# Environment

**状态：Frozen Target Architecture。** Environment 取代“Competition Field 是框架核心”的叙事；当前比赛 Field 只是一个具体 Profile。

Environment 表达 coordinate reference、map、named locations、zones、geofence、landmarks 和静态语义信息。它可向 World Model 提供场景上下文，供 Mission validation 与 Planning 读取。Environment 不包含 Vehicle 控制逻辑，也不替 Mission 决定 Action 顺序。

Profile 可为 `none`、`generic_gps`、`generic_local`、`campus`、`warehouse` 或 `cuadc_2026`。不同 Profile 必须明确坐标参考与数据来源；是否可用于具体 Mission 需经过验证。CUADC Field Reference 只属于当前实现/示例，不升格为所有环境的坐标规范。相关映射见[CUADC 示例](../examples/cuadc_2026.md)。
