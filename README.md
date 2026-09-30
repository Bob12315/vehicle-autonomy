# Vehicle Autonomy Framework

Vehicle Autonomy Framework 是面向多旋翼、无人车、固定翼、VTOL 及未来自主移动平台的**可复用自主系统框架**。它通过合同、插件和受控执行边界组合 Vehicle、Sensor、Perception、World Model、Mission、Action、Intelligence、Protocol、Transport 与 Deployment。通用 Core 不绑定特定比赛、机型、飞控、计算板或感知模型。

完整的职责、数据流、依赖规则和目标包归属见 [V1 目标架构](docs/framework_v1.md)；时间、坐标、状态、Effect 和端口的冻结语义见 [V1 基础合同冻结规范](docs/foundation_contracts_v1.md)。这两份文档描述设计目标，不代表其中的组件已由当前代码实现。

## 当前实现

根目录目前提供 P1 基础合同、P2 离线 World Model 状态链、P3 Typed Action/Mission 决策链及 P4 假端口控制边界。通用 TransformTree 求解静态/动态 Frame 关系。另有只读 ArduPilot/MAVLink parsed message 到标准 VehicleState 的适配代码，尚未接物理链路。P3 Runtime 只产生 Effect 请求；P4 Execution 可在显式授权、双 SEND 与 Safety 检查后向假命令端口提交，测试排队、撤销、deadman 和停止状态。**尚无**经过设备验收的生产车辆连接、Web UI、相机进程、飞控连接或服务器部署。当前 CLI 只提供状态查询。

车辆发送默认关闭。P4 离线 Execution 需要系统 SEND、Action SEND、有效 Lease、活跃会话和显式 `VehicleSafetyPolicy`；假端口在模拟写入前重新检查代际、会话和期限。断链时停止结果保持未确认。旧演示网关仍使用旧 Effect 测试端口。根目录 CLI 未装配真实端口或策略，不能据此宣称已支持实机飞行。

```bash
python -m app.main status
python -m unittest discover -s tests -v
```

[当前实现边界](docs/architecture.md)记录已有能力与限制。[迁移计划与记录](docs/migration_plan.md)给出从合同、状态链到控制与设备接入的阶段顺序。[历史程序说明](docs/migration.md)介绍 `legacy/cuadc_2026/`：它完整保存旧应用的代码、配置、测试和资源，供后续逐项评估复用；新根目录不导入该目录。
