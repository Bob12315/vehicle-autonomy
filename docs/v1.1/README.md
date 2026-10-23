# V1.1 改造记录

本目录记录七模块迁移完成后的 V1.1 开发，不替代两份根目录架构基线。

- [阶段一原始任务](phase1-task.md)：用户提供的完整验收范围。
- [阶段一基线审计](phase1-baseline.md)：复用项、缺口与测试基线。
- [阶段一历史报告](../PHASE1_MAVLINK_CONTROL_REPORT.md)：原开发侧两次真实仿真结果，保留不改写。
- [原机器证据索引](phase1-evidence.json)：原两轮量化结果、日志 SHA256、进程身份。
- [第二轮修复历史报告](../PHASE1_REMEDIATION_REPORT.md)：两个 P1 和两个 P2 的开发侧记录，保持不变。
- [第二轮修复证据索引](phase1-remediation-evidence.json)：原两轮完整回归、重放/过期故障及日志哈希。
- [第三轮定向修复报告](../PHASE1_REMEDIATION_ROUND3_REPORT.md)：回绕重放根因、接收认证、UNKNOWN、正常控制与使用限制。
- [第三轮证据索引](phase1-round3-evidence.json)：374 项单元测试、两轮真实 A–F、签名下行与回绕故障证据。

原开发侧记录为 350 项单元测试、两轮 Rover/Copter A–F、12/12 真实仿真场景通过；
第二轮修复的开发侧记录为 365 项通过，但第二轮独立审查仍为 FAIL。
第三轮仅定向修复回绕后的状态确认，374 项单元测试和两轮完整真实回归均通过，
当前状态为 **READY FOR RE-AUDIT**，等待独立审查，不宣布最终 Phase 1 验收通过。

本次只开发 ArduRover / ArduCopter 的 MAVLink 基础通信和安全控制。
阶段二、Plane 专属控制、外部感知/导航/智能和实机控制均不在范围内。
