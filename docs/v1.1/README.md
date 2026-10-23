# V1.1 改造记录

本目录记录七模块迁移完成后的 V1.1 开发，不替代两份根目录架构基线。

- [阶段一原始任务](phase1-task.md)：用户提供的完整验收范围。
- [阶段一基线审计](phase1-baseline.md)：复用项、缺口与测试基线。
- [阶段一最终报告](../PHASE1_MAVLINK_CONTROL_REPORT.md)：开发与两次真实仿真验收结果。
- [机器证据索引](phase1-evidence.json)：两轮量化结果、日志 SHA256、进程身份。

阶段一已通过：350 项单元测试、两轮 Rover/Copter A–F 验收、12/12 真实仿真场景。

本次只开发 ArduRover / ArduCopter 的 MAVLink 基础通信和安全控制。
阶段二、Plane 专属控制、外部感知/导航/智能和实机控制均不在范围内。
