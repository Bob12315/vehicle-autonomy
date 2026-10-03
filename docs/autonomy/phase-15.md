# P15 CUADC 仿真业务链验收

状态：**PASS，限 localhost SITL/Gazebo 仿真。**

前置 P13/P14 的公开任务、对象输入和控制边界；最小非车辆合同独立提交 `ca4df82`，只读候选清单见 [迁移审查](cuadc_candidate_inventory.md)。旧源没有修改或执行，新根不导入 legacy 或外部 cuadc2026。

cuadc_demo：Mode→Arm→Takeoff→命名搜索点/区域→从新鲜 Observation 评分/去重/锁定→接近/Stop 稳定→仿真投放→HOME→Land→Disarm。Rover object_inspection 复用有限搜索/接近，无 flight/payload 能力。标签分数与业务步骤只在 applications/cuadc，通用 Core 不含比赛规则。目标来源白名单、odom Frame、质量、置信度、1 s 对象年龄、区域与位置变动都强制检查；无目标/过期/移动/丢失/超时明确失败，不读取 Oracle。

ReleasePayloadEffect 走 PayloadExecution 与专属 SimPayloadPort；双 SEND、scoped lease、generation/session/deadline、显式 PayloadSafety 在入队和 mutation 前持锁复核。目标对准 0.3 m、车辆速度 0.15 m/s、车辆状态年龄沿用已有 profile 3 s，对象年龄独立 1 s；库存只能 loaded→released。重复同 Envelope 幂等，其他 Effect 再投同载荷拒绝，待提交可取消，已执行不能撤回。ACK 后等独立载荷状态 producer 的 WorldObject 才 COMPLETED；Vehicle Envelope/Execution 严格拒绝载荷。

载荷为仿真库存状态和位置标记，不模拟弹道、不控制 Servo/PWM、不代表真实载荷。App 必须显式 --sim-payload；默认无载荷端口。消费后同一 App 不能静默补货。Mission/Action 只见世界/请求/结果，只有 Execution 调 controlled port。

测试：payload 合同、执行门控/最终 fence/取消/重复/拒绝/ACK≠完成、候选选择/错误目标/缺失/移动/丢失/对准截止/能力及编译；公开进程通过 Copter 两次独立业务运行 `autonomy-copter-b11ae436`、`autonomy-copter-2c7d26f4`，Rover `autonomy-rover-455951ed`，对象缺失与接近中目标删除 `business-faults-copter-c21edd3e`。物理接近、Stop、HOME、落地由独立 Gazebo Oracle 检查；载荷完成另需 EffectResult、库存和 WorldObject 一致。失败后显式 safe_recovery 上锁，未自动重试非幂等动作。

保留首次目标时间映射失败 `autonomy-copter-90838672`、早期 GPS fix/global capture 不一致导致的恢复拒绝报告；修复见 P14/P10。测试仅在 Run 创建前对特定原点证据未就绪拒绝等待最多 3 s，不重试 Arm/Takeoff/Release。Task status 带编译步骤/参数 hash；manifest 带 Git SHA、工作树状态与根源代码指纹。最终完整回归 `suite-3501a226` 的 cuadc_first、cuadc_second、rover_inspection、business_faults 与视觉替换 visual_business 全 PASS；原验收数值/场景保留。29 阶段、21 场景、173 项当时单元测试零失败/跳过，最终 177 项单元/合同测试亦全通过，见 [总审计](completion-audit.md)。

阶段实现提交：`fd1113f`。原点/GPS capture 修正独立提交 `a1880f9`；取消尚未写出的请求见 `0afe6be`。复现使用总审计中的完整回归命令，单场景可用 `python -m tests.simulation.autonomy_process --kind copter --allow-send --mission cuadc_demo --objects`；需设置自有 SITL/plugin build 路径，详见仿真 README。
