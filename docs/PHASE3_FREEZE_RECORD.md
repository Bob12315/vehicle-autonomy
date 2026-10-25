# Phase 3 冻结记录

**状态：FROZEN，限定受信本机仿真范围。** 用户明确授权冻结后，重新执行完整正式
验收并核对原始证据、交付与清理，全部通过。本记录是修复后的验收和用户授权冻结，
不冒称一次新的独立第三方复审；前三轮独立 FAIL 及其历史证据完整保留。

## 冻结对象

- 实际受测及冻结实现：`43d849fef21bc432eff536a00da43fb13a8c0e25`。
- 冻结标签：`phase3-frozen`，注释标签直接指向上述受测提交。
- 受测源码、测试、脚本、配置及仿真输入 SHA-256：
  `f28beeca74f9ba209506e7b59d60c5d8f96e0802708712c9b24862d72eb09794`。
- 完整正式运行前后摘要一致；开始时工作区干净。冻结说明和证据索引在之后的纯文档
  提交归档，不把文档提交冒称为另一个经过完整车辆验收的实现。

审查中发现的 R3-P2-A 已由冻结实现修复：HTTP 作业在启动、轮询、取消及自动/手工
恢复时绑定 Provider ID、epoch、resource ID 和 Job ID；v2 请求/响应身份围栏阻止
endpoint 切换期间认领另一代际的同号终态。详见
[修复报告](PHASE3_HTTP_IDENTITY_FIX_REPORT.md)和[协议合同](phase3/EXTERNAL_ACTIONS.md#http-job-protocol-v2)。

## 本次完整正式验收

正式入口：

```bash
./scripts/test_phase3_actions.sh --allow-send \
  --sitl-bin-dir artifacts/phase2-control/ardupilot-source/build/sitl/bin \
  --run-dir artifacts/phase3-round3/freeze-43d849f-1
```

本地时间（Asia/Ulaanbaatar，UTC+08:00）：2026-10-25 22:57:27 至
2026-10-26 00:12:44，约75分钟。实际只启动拥有者为level6的隔离SITL二进制、
新建的自有Gazebo world和loopback端口；没有串口或实车连接。

| 项目 | 本次结果 |
|---|---|
| 全量单元 | 512项通过，零失败/错误/跳过；嵌套旧回归自身再次运行全量单元也通过 |
| HTTP身份新边界 | 11项真实Provider/HTTP/代际切换、错误/缺失身份及可信恢复正反例通过 |
| 原外部恢复边界 | 真实ROS Service提交后异常、HTTP已知/未知ID跨进程恢复全部通过 |
| Provider A–K和混合责任 | 真实多进程矩阵与两组未修改VehicleActionDriver的Rover混合场景通过 |
| Phase3三车型 | 两轮Rover/Copter/Plane各正常与故障，共12个场景通过；两轮A–G全通过 |
| Web Action Lab | 两轮真实headless Chrome运行、刷新同实例、取消反馈和物理停车通过 |
| 外部常规接口 | 两轮Native/HTTP/真实ROS各11项通过 |
| Phase1/2完整回归 | 两轮三车型共18个原场景通过，包含协议、物理、故障与清理 |
| Wheel | 新wheel独立安装，CLI实际启动、默认无车辆与真实DDS调用通过 |

正式[主汇总](../artifacts/phase3-round3/freeze-43d849f-1/summary.json)、
[原回归汇总](../artifacts/phase3-round3/freeze-43d849f-1/phase2-regression/summary.json)、
[最终核对](../artifacts/phase3-round3/freeze-43d849f-audit/final-audit.json)。
本次结果属于新冻结实现，未使用旧候选的仿真通过记录替代重跑。

## 原始证据与交付核对

24份原始代理日志共606,041行，固定抽样解码29,860帧，字段/CRC记录无不一致，
发送序号无异常。20个含Writer的场景，其原始写帧多重集/次数与代理tx_attempt
一致。两轮Plane故障在注入后均实际收到目标ACK 1、丢弃1、转发0、应用收到0。
38份代理/应用接收日志没有保留SETUP_SIGNING。

Gazebo原始轨迹分别复算三车型及原Phase2物理结果；Plane目标从实际COMMAND_INT
解码，没有把ACK或模式配置成功当作到达/着陆。两轮浏览器实例ID均可对应真实
Action，刷新保持同ID且无JS错误。原始计算保存在冻结audit目录的 `physical.json`、
`physics-phase2-regression.json`、`other-physics-phase2-regression.json`、
`wire-freeze-43d849f-1.json`和`wire-details.json`。

新wheel的216个Python模块、44个运行资源和6个Web静态文件匹配源码，18项catalog、
默认无车辆，主应用未导入rclpy。wheel SHA-256：
`bbc3571519ff6bbcb3755438e513cd401398b955e6bcd474cecdc081721c46dc`。
已安装wheel的CLI与实际ROS/DDS任务均运行成功，managed资源释放。

32个正式自有SITL/Gazebo fixture的私密文件、EEPROM和SITL state全部清理；记录的
PID/start_ticks不存活，相关17个车辆/代理端口可绑定。36个签名epoch摘要互异。
HTTP端口另行检查可重新绑定，无本次相关应用/worker/Provider进程残留；wheel临时
认证文件已删除。UNKNOWN reservation作为非敏感证据保留，没有通过清空记录恢复。

旧正式证据1461项、HTTP修复证据263项、历史保护2052项重新核对哈希无变化；
原第三轮独立FAIL报告与归档副本一致。所有新原始材料位于
`artifacts/phase3-round3/freeze-43d849f-1/`和`freeze-43d849f-audit/`，
大小/哈希见[冻结证据索引](phase3/freeze-evidence.json)。

## 冻结边界

本次冻结依赖同一受信OS账户、固定共享本机Registry、诚实Provider身份与终态及
可靠本地rename/fsync语义。外部HTTP Provider必须实现v2协议；不支持时不能退回旧
endpoint/Job ID查询，也不能删Ledger、换scope或新建空目录解除未知占用。

车辆仅限明确自有的本机SITL/Gazebo与已测profile。默认双SEND仍关闭；Lease、TTL、
Session/Generation、唯一Writer和UNCONFIRMED规则保留。Plane取消不能零速停车，
空中不做Disarm；不确定飞行结果仍保留资源。HardwareReadOnly保持只读，
hardware_controlled仍拒绝。

不包含跨主机锁、恶意Python隔离、通用ROS Trigger恢复、Mission Graph、AI新能力或
实车部署认证。MAVLink签名顺序不是请求UUID，原协议关联限制继续适用。

**Phase3到此冻结并停止，不开始Phase4。**
