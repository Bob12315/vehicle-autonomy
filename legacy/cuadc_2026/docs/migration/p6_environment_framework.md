# P6 Environment 框架边界

**状态：P6 框架层已落地；CUADC 场地细节和 UI 切换仍待后续实现。** 本轮按“只修改框架，具体细节之后完善”实施，不改比赛坐标、Mission JSON、Web 页面或实机控制流程。

| P6 项 | 本轮实现 | 待补内容 |
| --- | --- | --- |
| Environment Contract | `contracts/environment/` 定义不可变 `EnvironmentProfile`、`EnvironmentSnapshot`、`CoordinateReference`、`NamedLocation` 与读取 Port | Zone、Geofence、地图、landmark 的具体契约与数据；当前没有实际消费者需求 |
| Field Migration | `environments/cuadc_2026/` 提供现有 FieldReference 的只读适配器；WorldSnapshot 从该边界取得 EnvironmentSnapshot | `field/` 仍拥有现有校准、坐标变换与比赛几何；未来逐项迁移，保留兼容导入直到生产链完成切换 |
| Generic Environment | `EnvironmentCatalog` 注册 `none`、`generic_gps`、`generic_local`、`cuadc_2026`；前三者不虚构坐标或位置数据 | Web UI 的 Profile 选择、持久化、运行中切换校验与配置细节；生产默认仍固定 CUADC，避免让旧 Field Action 在通用 Profile 下误运行 |
| Mission 解耦 | 候选 Core 的 Mission 编译器与参数解析器支持 `$environment.locations.<name>` 及字段引用；引用缺失或 Field 参考未确认时，子 Action 启动前失败关闭 | 具体 Mission 模板仍保留原坐标；用户后续提供命名位置及 Mission 规则后，再选择一个 Mission 完整迁移和验证 |

WorldSnapshot 现在可携带 EnvironmentSnapshot，原 `environment_reference` 字段仍供 P5 消费者兼容读取。生产循环对 Field 只读取一次快照，再投影两种形式，保持版本一致。Environment 代码不发送命令，也不决定 Mission 顺序。

`NamedLocation` 保留坐标系，引用解析只读取明确命名的位置，不做隐式 FIELD/GPS/LOCAL 坐标转换。新 Profile 未配置位置时保持空集。当前实机默认仍为 CUADC Field；`executor.send_commands: false`、系统 SEND / Action 双门控、连续命令停止机制和既有 Field 校准行为未改变。

## 验证

契约测试覆盖四种 Profile、CUADC 投影、Frame 一致性、WorldSnapshot 携带环境快照，以及 Mission 位置引用的成功和缺失拒绝。静态测试约束通用 Environment 不导入 Field/Application。全量测试结果为 754 passed、3 failed；3 项失败均在 P6 前已存在，分别涉及 strict profile 行数限制、align_descend 行数限制和 goto settle time。架构边界及稳定核心校验通过。运行测试不连接真实飞控。
