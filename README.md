# Vehicle Autonomy Framework

Vehicle Autonomy Framework 是面向多旋翼、无人车、固定翼、VTOL 及未来自主移动平台的**可复用自主系统框架**。它通过合同、插件和受控执行边界组合 Vehicle、Sensor、Perception、World Model、Mission、Action、Intelligence、Protocol、Transport 与 Deployment。通用 Core 不绑定特定比赛、机型、飞控、计算板或感知模型。

完整的职责、数据流、依赖规则和目标包归属见 [V1 目标架构](docs/framework_v1.md)。该文档描述设计目标；目标中的组件不等于当前已实现功能。

## 当前实现

根目录目前提供车辆无关的 Mission 与 Action 合同、Action 注册和 Mission 校验、最小 `WorldSnapshot` 合同，以及带保护的 Execution 边界。**尚无**生产车辆适配器、Mission 调度器、Web UI、相机进程、飞控连接或服务器部署。当前 CLI 只提供状态查询。

车辆发送默认关闭。Execution 必须同时获得系统 SEND、Action SEND 和显式 `SafetyPolicy` 允许，才能提交到 `VehicleCommandPort`；根目录 CLI 未装配真实端口或策略。现有接口不能据此宣称已支持实机飞行。

```bash
python -m app.main status
python -m unittest discover -s tests -v
```

[当前实现边界](docs/architecture.md)记录已有能力与限制。[历史程序及迁移原则](docs/migration.md)说明 `legacy/cuadc_2026/`：它完整保存旧应用的代码、配置、测试和资源，供后续逐项评估复用；新根目录不导入该目录。
