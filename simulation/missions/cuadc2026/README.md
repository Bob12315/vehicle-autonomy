# CUADC 2026 救援任务模板

`rescue_2026_full_auto.json` 是当前框架的 Mission Studio schema 2 模板。
`rescue_2026_source.json` 保留用户提供的原始任务，供参数与步骤核对，不能作为
当前框架的执行文件。模板构造位于 `app/scenarios/cuadc/rescue.py`，不会自动运行。

在仿真中心选择 `CUADC2026`、`copter_rescue` 和 `home` 出生点。车辆上线后，
Mission Studio 模板库提供 `Rescue_2026_FullAuto`；复制、选择当前实例、校验、
发布，再显式开启任务 SEND。普通 Copter 没有救援能力，完整任务的校验会拒绝。
本机软件和 PT 权重由 HostEnvironment 的 `vision_python`、`rescue_model` 指定，
权重必须匹配 `configs/perception/rescue_2026_pt.json` 的 SHA256。

流程：估计器稳定等待 → GUIDED/Arm → 4.5 米起飞 → (0,32.5,5) 采样、
整理与选桶 → 最多两次 3 米接近、重新确认目标、对准下降到 1.1 米、投放、
爬升至 2.5 米 → 六个 56/59 米侦察航点 → (0,0,4) 返航 → 2.5 米获取 H →
对准下降到 0.3 米 → Land。原 change_speed 步骤落实为每航段速度限制。

任务参数采用当前框架的 odom ENU，场地前方为 +Y。`bucket`/`H` 模型不能区分
原评分表的 bucket_1/2/3，所以同类桶按实际置信度及标识排序；不虚构分值类别。
一个观测桶接收两瓶，两个桶各接收一瓶。通道 8 → payload_1，通道 9 → payload_2。
释放/保持值保留原任务的 1800/1370、1835/1335，仅用于识别已审查的配置，
Gazebo 投放通过独立 PayloadExecution 发布 detachable-joint 请求，未发送实机 PWM。

原 continue-on-failure、无观测中心点投放、对准超时当成功均未沿用。目标临时
丢失时立即请求零速度，最多等待 3 秒重新获得同一锁定目标；等待期间不下降。
重新接近另一桶后，由独立 ConfirmTarget 在同一来源、同一类别、0.4 米内唯一
匹配时更新跟踪标识。不存在或有歧义时失败。目标身份计划有效期 180 秒，
每次运动/投放仍检查原始捕获时间与当前 1 秒内的有效视觉观测，不能用计划寿命
延长传感器数据、Effect TTL、Lease 或授权。

地图、识别、脱离确认、完整任务、投中桶是不同的验收项。投放完成只表示收到了
独立瓶体脱离状态，不能据此声称投中桶。原虚拟相机偏移保留为显式参数，
当前几何只适用于这一固定相机、平面和出生点组合，不是实机标定。

本机完整 Mission、H 对准降落及清理的实测范围见 `docs/RESCUE_2026_LOCAL_PT.md`。
桶使用 PT，黄底黑 H 使用独立像素几何来源；不把桶类别预测重命名为 H。
