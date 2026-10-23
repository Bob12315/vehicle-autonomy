# 阶段一基线审计

- 起点：`7444885`，分支 `feat/v1.1-phase1-control`，开始时工作区干净。
- 已阅读：AGENTS、README、两份架构基线、实现边界、附件任务及现有协议/遥测/运行时/仿真代码。
- 七模块迁移和仓库 Legacy 删除已经完成，不重新迁移。
- 复用：pymavlink MAVLink2 codec、Session、独占 Writer、Execution、Authority、双 SEND、车型翻译器、Safety、源时钟、OwnedSimulation、Gazebo 独立真值、TCP 故障代理及既有物理场景。
- 缺口：现有归一化状态只公开姿态/位置/电池/模式；没有逐消息可用性、EKF、告警、ACK 和来源/会话诊断；只发布接收时的快照，查询时的字段时效不透明；必须用新增测试覆盖异常、重复/倒序与会话边界。
- 接收与发送现已分离；SEND 默认 false；只在自建 loopback SITL 中开启。不会连接任何串口或实车。
- 环境预检通过：Python 3.12、pymavlink 2.4.49、pyserial 3.5、Gazebo 8.15、现有 Copter/Rover 二进制和 Gazebo 插件可用。
- 单元基线：342 项全部通过（31.715 秒，无失败）；完整结果见 `artifacts/phase1-control/baseline-unit.log`、`preflight-baseline.json`。
- 既有迁移回归：342 项单元通过，21 个物理场景 19 PASS / 2 既有 oracle 启动失败；P26 导航未通过。保留原报告与日志，这些历史状态不冒充本阶段结果。

验收新增独立入口，覆盖 A–F，两轮独立 run ID、原始协议/归一化数据/物理真值/资源清理证据。任何失败保留日志，修复后重新完整运行。
