# Vehicle Autonomy Framework

Vehicle Autonomy Framework 是面向多旋翼、无人车、固定翼、VTOL 及未来自主移动平台的**可复用自主系统框架**。它通过合同、插件和受控执行边界组合 Vehicle、Sensor、Perception、World Model、Mission、Action、Intelligence、Protocol、Transport 与 Deployment。通用 Core 不绑定特定比赛、机型、飞控、计算板或感知模型。

完整的职责、数据流、依赖规则和目标包归属见 [V1 目标架构](docs/framework_v1.md)；时间、坐标、状态、Effect 和端口的冻结语义见 [V1 基础合同冻结规范](docs/foundation_contracts_v1.md)。这两份文档描述设计目标，不代表其中的组件已由当前代码实现。

## 当前实现

根目录目前提供车辆无关的 Mission 与 Action 合同、Action 注册和 Mission 校验，以及 P1 基础合同：时间/坐标、观测、车辆自报状态、定位、版本化 `WorldSnapshot`、Typed Effect、VehicleCommand 和窄端口。现有 Execution 仍是旧 Effect 的演示边界，尚未接入新命令合同。**尚无**生产车辆适配器、Mission 调度器、Web UI、相机进程、飞控连接或服务器部署。当前 CLI 只提供状态查询。

车辆发送默认关闭。现有演示 Execution 必须同时获得系统 SEND、Action SEND 和显式 `SafetyPolicy` 允许，才能提交到它的旧 Effect 测试端口；P1 `VehicleCommandPort` 尚未由该网关使用。根目录 CLI 未装配真实端口或策略。现有接口不能据此宣称已支持实机飞行。

```bash
python -m app.main status
python -m unittest discover -s tests -v
```

[当前实现边界](docs/architecture.md)记录已有能力与限制。[迁移计划与记录](docs/migration_plan.md)给出从合同、状态链到控制与设备接入的阶段顺序。[历史程序说明](docs/migration.md)介绍 `legacy/cuadc_2026/`：它完整保存旧应用的代码、配置、测试和资源，供后续逐项评估复用；新根目录不导入该目录。
