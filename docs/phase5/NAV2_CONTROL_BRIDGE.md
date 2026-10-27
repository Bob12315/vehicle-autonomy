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

## 原生链路早期开发验证

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
早期记录未包含运动桥。后续开发桥已实际接入，但尚不能把该配置声称为已通过完整物理导航验收。

真实全图 SROS2 Enforce 权限正在验证。固定角色分别约束 raw/smoothed/final
发布、管理 Goal 和只读 viewer；命名空间本身不构成认证。早期全图启动失败
独立保留在 dev-nav2-secure-*，尚不能宣称最终导航安全装配已完成。

开发检查点：618 个单元测试通过；dev-nav2-secure-17/18 真实加密图通过。
加强原始零速新鲜度断言后 dev-nav2-secure-19 也通过；没有延长零速时间戳，
而是在真实 Wait 子目标运行期间等待通道建立后再正常取消以取得新零速。
只读 viewer 的最终发布/Goal 客户端均由实际 middleware 拒绝，
管理客户端仅一个 Navigate Goal，原始 producer 时间限定的最终控制持续有效。
所有运行清理凭据、进程组和端口。该检查点没有装配实际车辆桥，不能声明 Phase 5 完成。


## 受控运动桥开发增量

当前新增 Rover 专用 NativeRoverNavigation，沿用同一个 ActionRuntime、
RoverStream、Execution、Authority 与 Writer。NativeNavigationJob 在现有
P3 外部生命周期登记后才启动原生 cohort；与车辆 Typed Effect 分别证明退出。
实际写入时还重新验证固定的扫描、原生位姿/变换/地图、AP Session 和运动界限。
所有源期限仍为原值；等待、重读元数据、准备 Goal 和重新接收均不能续期。
详细来源与退出合同见 [NATIVE_SOURCE_AND_EXIT.md](NATIVE_SOURCE_AND_EXIT.md)。

本轮开发中发现并修正元数据读取起点与并发发布的竞态、可选认证时钟路径
50 ms 空闲读取阻塞、初始加密通道建立时的旧零速，以及逻辑结果早于 DDS
进程退出的问题。逻辑结果可触发车辆停车，但整个 cohort 未安全结束时，
外部资源仍被占用。控制器的准备阶段只接受真实零速且禁止任何车辆 Effect；
新的当前位姿 FollowPath 准备只在前一个原生结果确定成功后才能再次提交。
正式 Navigate Goal 仍只有一个，不重试 UNKNOWN。

原生 StoppedGoalChecker 的 stateful=false，位置 0.25 m、角度 0.15 rad、
停止速度 0.05 的参数保持不变；持续检查 XY，以避免首次进入范围后漂出仍
被原生检查器接受。依据为 [Nav2 1.3.13 SimpleGoalChecker 官方源码](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_controller/plugins/simple_goal_checker.cpp)。
应用另以独立新鲜 World 位姿核查目标，原生 SUCCEEDED 不足以宣告成功。

开发失败原件保留：dev-native-motion-9/10 的数据失效、11 的过期写入拒绝、
12 的未生效接触 Topic、13 的时钟查询暂停范围错误、14 的位姿过期、
15 的独立目标证据不足、16 的首个运动爬升拒绝、17 的结果传播延迟。
所有实际无效指令继续被拒绝；失败没有改成 PASS。
真实 Gazebo Contact 插件的 Topic 在 contact/topic，不能以配置存在代替
实际接触数据。原生接口依据为 [Gazebo Contact 实现](https://raw.githubusercontent.com/gazebosim/gz-sim/gz-sim8/src/systems/contact/Contact.cc)。
接触计数包含全部实际报文；地面日志有 50 Hz 抽样及 32 MiB 上限，原始
计数、被抽样数量和未知实体都另记，任何探针错误使验收失败。

独立 wheel 开发检查 dev-native-wheel-1 已验证安装目录、既有 Web 默认无
车辆入口和实际安装的 C++ 源码编译；后续正式受测提交还须重建验证。
上述均为开发证据，完整 A–I、两轮正式仿真、Mission/Web/Provider 装配及
旧阶段完整回归尚未完成。
