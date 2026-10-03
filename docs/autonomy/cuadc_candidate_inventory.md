# CUADC 只读迁移候选清单

外部只读参考 `/home/level6/uav_ws/cuadc2026/` HEAD `9af97f440f086e81192e5ef9cc31cefda47a26af`；归档 `legacy/cuadc_2026/` 保持不变。仅读源文件和 git 元数据，不运行旧测试/应用，也不生成旧树文件。两个版本并不相同；原始 actions 位于 missions/common/actions，归档重新分包且部分逻辑版本不同，不能当作逐字同一版本。

| 模块 | 输入/输出 | 依赖、时间/Frame、安全 | 决定 |
|---|---|---|---|
| takeoff | vehicle 状态/字段高度、yaw/模式/解锁/起飞；dict Effects | 状态增量/超时，但旧字段时间和 FIELD/GPS 转换依赖 | 概念复用，P12 重写，禁止旧 Mode/Arm port |
| goto_waypoint | FIELD/global 航点、速度和阈值；控制请求 | 现场 origin/heading；旧拒绝/完成生命周期 | 命名 odom 目标 P12/P13 重写 |
| target_lock | 图像中心、FOV、云台/机体姿态；目标位置/控制请求 | 依赖 guidance 投影及旧感知快照；无标定不能空间定位 | P14 Observation 选择重写；图像几何 P17 |
| select_drop_targets | 对象列表、bucket 权重/分数；目标排序 | 比赛标签评分 500/300/100、去重半径和 target_count 不进 Core | 应用配置重写，只用 WorldObject 来源/版本 |
| align_descend | 图像/位置误差、机体/yaw/高度；FlightCommand/ConditionYaw | 内部 monotonic 与控制帧；complete_on_timeout 可将超时视为成功 | 重写有限接近/对准，超时失败，受控 Stop |
| payload_release | payload/target、Servo channel/PWM；set_servo 字典 Effects | MAV_CMD_DO_SET_SERVO；等待秒数/更新次数后宣称完成，无物理载荷观测 | 不迁移 Servo 行为；独立非车辆 Effect/Execution/仿真状态观测 |

源摘要（SHA256）：

| 模块 | 归档 | 外部参考 |
|---|---|---|
| takeoff | `eccc81f1d2543114768ea1e683eebece982ed92f4fe4b12817d4a995f7857c6b` | `d2e0af0091d3915eee6dc3d5e39da6f16d563f4115e61998f6c6d0bd157ae935` |
| goto_waypoint | `6affba08350dac384512e56ce237dbb2f0271eb1bd78808d3a61180c15339e0f` | `4c11c819f3ceb2120a98507523f1f0400e249d6e9cc5fd34f0a1160d1042b072` |
| target_lock | `759289c566c953b9d39f4758fb5016b09d99daeabed98780306cee9049f2a57e` | `64ab25a8ab53d3857b24d587b0db83e365d89c174b9639107be997cadde93e40` |
| select_drop_targets | `98cd8556bfedc9af72b625cd2d1f28e73aef93deeece0a83a052b7704c95b3f9` | `84b56812dafd9bbd4a948405c535384dd862e052c4b63b48a9328c001cd5f775` |
| align_descend | `acaf40f1156453fc079ff753bf269d2967b63305491aa174b4e818b8325a6aa8` | `d2d4237db5cd4572febd590d4634e20fe6a53d14cc24416ecad3ca0db5ea75c4` |
| payload_release | `680cac71de92edaf4cd7e84f5cbdd9d23b367b15a767a57abb7ec60725a3969a` | `3297252682b94c480ef44934d81d3529bfb7ce0feb2b82c9e77c874c0fda83c7` |

外部 payload_release 比归档增加串行输出及 1 s Servo ACK 隔离间隔；这改善旧命令关联但仍不是实际投放证据，两者都不纳入新运行时。takeoff、goto、target_lock、align_descend 的旧结果与控制 Frame 需依赖旧 telemetry/guidance/context 服务，均不复制整个模块。

`rescue_2026_full_auto`、`drop_two_targets`、`recon_gps` 的旧 FIELD/global 坐标、飞行高度、任务排序、失败继续策略仅作比赛参考。新仿真链默认 STOP、max_attempts=1，命名搜索点/区域由 Environment 解析，单次目标投放为最小可复用链，不宣称完整比赛策略。

`app/bootstrap.py` 装配 LinkManager、command adapter、后台遥测、YOLO UDP；依赖旧运行时和隐式硬件生命周期，暂缓、不迁。新 App 组合只提供 Snapshot；Action 不访问传感器、Gazebo、命令端口。返航复用 P12 版本化 HOME + Stop 语义；旧 RTL/返航相关 dict 行为不继承。

P15 合同缺口：现有 ActionDecision/ExitDecision 和 Mission envelope 仅允许 VehicleEffect。投放不是车辆运动，不能塞进 VehicleEffect 或翻译 Servo。需新增独立 PayloadEffectEnvelope/ReleasePayloadEffect/受控载荷端口，最小扩展 Action 的 allowlist，车辆 Envelope/Execution 保持严格拒绝载荷。合同理由、兼容性和测试独立提交后才装配业务。
