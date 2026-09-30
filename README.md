# Vehicle Autonomy Framework

Vehicle Autonomy Framework 是面向多旋翼、无人车、固定翼、VTOL 及未来自主移动平台的**可复用自主系统框架**。它通过合同、插件和受控执行边界组合 Vehicle、Sensor、Perception、World Model、Mission、Action、Intelligence、Protocol、Transport 与 Deployment。通用 Core 不绑定特定比赛、机型、飞控、计算板或感知模型。

完整的职责、数据流、依赖规则和目标包归属见 [V1 目标架构](docs/framework_v1.md)；时间、坐标、状态、Effect 和端口的冻结语义见 [V1 基础合同冻结规范](docs/foundation_contracts_v1.md)。这两份文档描述设计目标，不代表其中的组件已由当前代码实现。

## 当前实现

根目录目前提供 P1 基础合同、P2 离线 World Model 状态链、P3 Typed Action/Mission 决策链、P4 控制边界，以及 P5 ArduCopter/MAVLink/TCP 插件。通用 TransformTree 求解静态/动态 Frame 关系。P5 将只读状态适配、受控命令端口、MAVLink 编解码和字节传输组合，在内存传输与本机 SITL 验证。P3 Runtime 只产生 Effect 请求；P4/P5 Execution 仍须显式授权、双 SEND 与 Safety。**尚无**经过实机验收的生产车辆连接、Web UI、相机进程或服务器部署。当前 CLI 只提供状态查询。

车辆发送默认关闭。P5 命令端口在唯一字节写入点前重新检查系统 SEND、Action SEND、Lease、代际、会话和期限；断链时停止结果保持未确认。TCP 连接只能由调用方显式创建，根目录 CLI 未装配端口或策略。旧演示网关仍使用旧 Effect 测试端口，不能据此宣称已支持实机飞行。

```bash
python -m app.main status
python -m unittest discover -s tests -v
```

ArduCopter 插件使用 [requirements-p5.txt](requirements-p5.txt) 中的可选依赖。本机 SITL 验证需先自行启动 ArduCopter 的 TCP 5760 端口，再显式运行 `PYTHONPATH=. python tests/manual_p5_sitl.py --allow-send`；脚本仅连接 `127.0.0.1`，确认未解锁后请求 `GUIDED` 模式并等待 ACK。它不会执行起飞或实机连接。

[当前实现边界](docs/architecture.md)记录已有能力与限制。[迁移计划与记录](docs/migration_plan.md)给出从合同、状态链到控制与设备接入的阶段顺序。[历史程序说明](docs/migration.md)介绍 `legacy/cuadc_2026/`：它完整保存旧应用的代码、配置、测试和资源，供后续逐项评估复用；新根目录不导入该目录。
