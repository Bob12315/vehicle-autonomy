# Nav2 控制桥：已实现的输入边界

当前仅完成桥输入合同和源 deadline 向 Action Effect 的传播；不能据此宣称 Nav2 已完成
ArduPilot 物理闭环。真实 Nav2 接收 worker、原生链路接线、导航 Action 与故障验收仍在开发。

NavigationBinding 必须同时绑定 Action、target、真实 provider/epoch、车辆 session、World
generation、goal 和最终发布端 GID。NavigationMailbox 只有一个当前样本，不保存队列历史；
校验原源时间/采集时间、接收时序、递增序号、FLU base_link、既有 Rover ±0.5 m/s 和
±0.35 rad/s 限制、0.3 m/s² / 0.5 rad/s² 加速边界。启动方必须先证明车辆静止，首个输入从
静止状态按实际采集时间爬升；紧急向零减速不因限加速度而延迟。原始样本 200 ms 失效，
重复收取或旧时间戳不能刷新；关闭后不可重新消费。GID 是本机装配检查，不声称其构成强认证。

ActionContext 由 Runtime 注入实际 Action ID、driver session 和 world generation。新增可选
ActionDecision.valid_until 只会缩短既有 TTL/deadline，不会授予或延长权限。Runtime 在回调
结束后获取新时钟，校验源时域并裁剪 EffectEnvelope.deadline；cleanup 仍使用原独立窗口。
最终 Writer 的 Authority/Guard/Lease/session/generation/TTL 检查不变。没有该字段的旧 Action
行为不变。独立外部 Job 的退出责任仍由 Phase 3 持久 Ledger 和 ExternalLifecycle 约束。

`bridge-contract-tests.log`：6 项确定性正反对照通过，包括正常爬升/制动、重复接收 999 次、
旧身份、错误时域、关闭后输出，以及回调耗时后实际 Driver dispatch 为 0。
`bridge-unit-590.log`：590 项完整单元通过。真实 Writer 与三车型物理回归仍须正式执行。

## 原生链路开发验证（未完成车辆桥）

`phase5_nav2_chain` 实际启动 native Planner、DWB Controller、Velocity Smoother、
Collision Monitor、Behavior Server 和 BT Navigator。`dev-nav2-chain-5/6` 在
Gazebo + signed SITL 下生成真实路径并观察连续最终速度、原生 Goal 取消；
没有装配车辆运动桥，车辆保持静止。只读 TIMESYNC 与车辆控制 Writer 必须
分开计数。上述开发记录不能替代正式导航或两轮 A–I。

Native Wait 的正常完成不发送零速；取消长 Wait 才会发送真实零速，可用于
受控 macro 的 PREPARING 阶段。Smoother 即使关闭普通重打时间戳，输入超时
减速仍会生成新 stamp。最终帧必须另有原始控制器 stamp/产生时间证据；
不匹配的帧拒绝，不能据最终接收时刻续期。ControllerEvidence 和
NavigationMailbox 均有固定容量和 200 ms 原始源年龄上限。

新配置保持 scan source_timeout=0.3、TF tolerance=0.2，禁用 native 需要
当前时刻外推 TF 的 base_shift_correction，采用保守扩大 footprint/stop
polygon。实际车辆桥启用前必须验证签名观测速度 <=0.4 m/s、偏航率
<=0.45 rad/s；300 ms 内的平移及车体旋转不确定性 <0.25 m 额外包络。
目前尚无实际运动桥，不能把该配置声称为已通过物理导航验收。

真实全图 SROS2 Enforce 权限正在验证。固定角色分别约束 raw/smoothed/final
发布、管理 Goal 和只读 viewer；命名空间本身不构成认证。早期全图启动失败
独立保留在 dev-nav2-secure-*，尚不能宣称最终导航安全装配已完成。

开发检查点：618 个单元测试通过；dev-nav2-secure-17/18 真实加密图通过。
加强原始零速新鲜度断言后 dev-nav2-secure-19 也通过；没有延长零速时间戳，
而是在真实 Wait 子目标运行期间等待通道建立后再正常取消以取得新零速。
只读 viewer 的最终发布/Goal 客户端均由实际 middleware 拒绝，
管理客户端仅一个 Navigate Goal，原始 producer 时间限定的最终控制持续有效。
所有运行清理凭据、进程组和端口。仍未装配实际车辆桥，不能声明 Phase 5 完成。
