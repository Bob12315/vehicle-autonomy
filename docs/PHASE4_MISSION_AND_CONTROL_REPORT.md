# Phase 4 Mission 与控制中心开发记录

状态：**FAIL（开发验证尚未完成，非最终交付结论）**。必须完成独立的两轮真实
验收、完整既有回归、安装和清理核验后更新本报告；不得把开发场景结果替代正式验收。

## 基线与范围

分支 `feat/phase4-mission-control`，起点
`e4a0b86f6cd30437beca49c0d402a9129468bb94`，标签 `phase3-frozen`
指向 `43d849fef21bc432eff536a00da43fb13a8c0e25`。实际冻结记录是用户授权的
受信本机仿真冻结，未发现新的独立 PASS 文书；此前三轮独立 FAIL 保持原样。
基线 512 项单元通过；保护清单 `artifacts/phase4-mission/baseline.json`
记录 3832 个历史文档及证据文件。未修改独立旧项目，未连接硬件。

## 实现

合同和限制详见 [Phase 4 使用与合同](phase4/CONTRACT_AND_USAGE.md)。
`contracts/mission.py` 定义不可变 MissionSpec、BlackboardValue、Truth 和只读端口；
`world/model/mission_inputs.py` 实现有界确定性事件、带原始来源与时间的只读查询；
`engine/mission/{graph,graph_runtime,journal}.py` 提供严格树图校验、版本锁定、
有界节点调度和崩溃一致性记录。逻辑节点不直接触碰车辆协议。

任务资源保留集成到同一个 ActionResources；子 Action 有不可序列化的进程内成员许可，
不能替代车辆授权。UNKNOWN 不启动普通恢复分支，逻辑终态不等于安全释放。
原 Typed Effect 和独立外部生命周期责任保持分离。重启不恢复旧 Action/SEND/Lease；
恢复要求固定部署绑定、可信车辆地面状态和独立外部 Provider 对账证据。

`app/web/mission_control.py` 复用 Action Lab 的 Registry、Runtime、Driver、认证和调度。
Studio 提供节点拖拽、连接、动态参数、验证、撤销/重做、布局/缩放、版本与 JSON 导入导出、
运行/取消、实际节点高亮、反馈与有界历史回放。Control Center 支持三车型的既有标准 Action、
AP 状态与航迹，以及受管理的 Rover/Copter 连续输入；Plane 原生飞行明确区分配置与物理到达。
不使用 Gazebo 真值控制车辆，不增加 Writer、不弱化原 200 ms cycle 及物理阈值。

## 开发验证与修复

最新开发全量单元：562 项通过，无跳过（`unit-dev-4.log`）。开发阶段已保存三车型真实
Mission 和 Chrome 操作结果，源代码尚在变更，因此不列为冻结正式验收。

保留的开发失败包括：观测夹具误解析空缓冲、隔离 Registry 夹具装配错误、Plane 调度时限触发、
只读重连夹具复用旧代理，以及 wheel 检查漏装声明的 MAVLink extra。分别修正夹具、减少无变化
Journal 提交、限制观测内存并保留完整文件日志、压缩只读状态切面、降低完整页面重复查询频率、
重建测试代理，以及按正常安装合同安装依赖；没有放宽原保护。新增断言证明原重复提交问题及
任务间资源插入问题在修复前稳定失败。所有失败目录和日志保留。

曾发现新测试误用既有 `mission_faults.py` 文件名，已恢复该原文件的基线字节，新测试独立为
`phase4_faults.py`；旧测试未删除。wheel 开发检查第二次通过，安装目录实际启动三页面、默认车辆
为零，逐字节验证源码与资源。正式结果仍须在冻结提交上重新执行。

开发边界现已通过：Rover/Copter 同合同的冲突、取消、失联、只读重连及新仿真可信恢复；
HTTP 混合作业退出异常/超时的独立责任保留与可信终态后恢复；Plane 跨 Mission/手动续接
和真实 AUTOLAND（落点误差 1.246 m），ACK 丢失时代理丢弃 1 帧、应用收到 0 帧，
16 次 packet sequence 回绕后旧 ACK/HEARTBEAT 重放均被拒绝，UNKNOWN 新接管 Writer 为零。

混合测试首轮正向对照因自定义 Action 误用通用 1 秒 Effect TTL 而如实 UNKNOWN；
新测试改为直接引用既有 SetMode 的 5 秒模式合同后通过，原安全阈值与标准 Action 未改变。
冻结前最新全量单元 565 项通过，无跳过（`unit-pre-freeze.log`，73.028 秒）。
冻结前清理审计通过：3832 项历史文件不变，22 个自有 fixture 的凭据/状态已销毁，
8 个相关仿真端口可绑定，没有登记的自有进程残留。

## 正式验收

首个冻结候选 `23f9dd84a31cd34989095aab0182ec6c9f740a1b` 的正式运行
`artifacts/phase4-mission/acceptance-23f9dd8-1/` 如实保留 FAIL：565 项单元、
第一轮三车型 Chrome Mission/Manual、Rover/Copter 故障恢复及 Plane 续飞/重放均通过，
混合测试第二种退出超时场景在 Driver 异步退出 Future 完成前直接解引用 `None`，导致测试异常。
原始日志显示 UNKNOWN 后约 54 ms 车辆退出完成；外部 Job 仍活动，资源未误释放。
只修改新测试：在 2 秒有界观察窗内要求真实 Driver release_safe 证据，同时断言外部 Job
仍活动和 Mission 占用未解除；不延长原 Action/Execution 退出期限，不把缺失证据当安全。
失败运行自有进程、端口及凭据已清理。修复须独立重跑，并在新冻结提交重新完成全套两轮。

尚未执行完成。受测 Commit、两轮 A–J、旧 Phase 1/2/3 全量回归、wheel、
输入哈希、历史完整性及资源/凭据清理将依据原始文件填写，不能提前声明完成。

## 剩余限制

仅限受信本机、固定 ProviderRegistry、诚实 Provider 和可靠本地原子存储，不提供跨主机锁或
恶意 Python 沙箱。Mission 最多 128 节点、256 Action、64 次运行；历史事件窗口 256 条，
Journal 最大 4 MiB，预算耗尽保守拒绝。没有实机控制、新感知融合或 AI 功能。
