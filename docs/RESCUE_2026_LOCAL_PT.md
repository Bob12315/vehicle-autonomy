# CUADC 2026 地图、救援模板与本机 PT 识别

日期：2026-11-05。当前入口是控制中心中的 `CUADC2026` 场景、
`copter_rescue` 车辆，以及 Mission Studio 的 `Rescue_2026_FullAuto` 模板。
这是一套显式自有的本机 Gazebo/SITL 配置，硬件继续保持只读。

## 使用

1. 重启 `./control-center`，在仿真中心选择 `CUADC2026`。
2. 车辆选择“CUADC 救援多旋翼 · 下视相机与双载荷”，出生点选择 `home` 后启动。
3. 在 Mission Studio 模板库复制 `Rescue_2026_FullAuto`，选择本次上线的车辆实例。
4. 校验、发布，确认实例绑定后显式开启任务 SEND 运行。模板不会自动执行。

本机 `environments/tools.local.toml` 已配置 `vision_python`、`rescue_model`。
其他机器应复制环境模板后填写自己的路径，不能提交本机配置。权重位于仓库外，
SHA256 必须与 `configs/perception/rescue_2026_pt.json` 一致。该配置可选 `cpu`
或本机 GPU `0`；主程序环境不安装 Torch，推理进入明确启动的独立工作进程。
车辆状态中的 `rescue_perception` 提供推理来源、原始捕获年龄和健康诊断。

## 迁移范围

原启动脚本使用 `cuadc2026_rescue.sdf`，嵌入固定下视相机 Iris。
原 world、field、相机与瓶体 SDF、原任务 JSON 已保留，来源摘要位于
`simulation/missions/cuadc2026/migration.lock.json`。独立 scene 去掉了内置飞机及
参考坐标轴，将无限碰撞平面换成 160 × 160 米有限地面；桶、侦察目标和标线
保持原几何。车辆由现有 VehicleRegistry、SimulationManager 单独装配。

Iris、云台网格与 Gazebo 插件继续来自 HostEnvironment 指定的外部软件；未复制
大型第三方网格、旧应用程序或旧 MAVLink 投放桥。专用模型及参数继续经过源文件
SHA 锁定和实例快照，发布／状态主题按独立实体隔离。

救援 profile 的起飞上限为 5 米，场地范围为 X [-5,5]、Y [-2,62]。
光学配置只准入固定 (0,0,0.195)、朝向 90° 的 home 出生点。普通 Copter profile、
标准 Takeoff/Goto 的原有限制不变；普通车辆缺少 `rescue_*` 能力时拒绝完整模板。

## 训练与模型

按用户指定训练仓库 README 的 `scripts/01_train_yolo.py` 方法训练，
未执行 ONNX/RKNN 转换。训练前复制了数据集，未修改原项目代码、标签或旧模型。
完整训练输出与数据摘要保存在仓库外的本机 rescue-2026 资源目录。

| 项目 | 本次值 |
| --- | --- |
| 预训练架构／输入 | YOLO11n / 640 |
| 训练轮数／批次／早停 | 150 / 8 / patience 50 |
| 环境 | Python 3.10.21、Torch 2.5.0+cu118、Ultralytics 8.3.163 |
| 训练／验证图片 | 375 / 140 |
| 类别 | bucket、H |
| best.pt 保存的 Precision / Recall | 0.97613 / 0.97808 |
| best.pt 保存的 mAP50 / mAP50–95 | 0.99069 / 0.84589 |
| 最终复验日志的桶 mAP50 / mAP50–95 | 0.984 / 0.837 |
| 权重 SHA256 | `f89ed69dd7639cc40689c4af3d97bdb6335c72c2e15aa86f056da52e61cbc4e4` |

独立 CPU 和 GPU 进程均用这份 PT 权重对验证图片做了实际推理。模型没有
bucket_1/2/3 类别，任务不会从普通桶预测中虚构分值类别。

数据集的 H 是白字黑底，而原救援地图为黑字黄底；实际返航画面中 PT 将黄底 H
误识别成桶。因此，桶继续由 PT 检测，黄底 H 由独立的
`yellow_disc_h_shape_v1` 图像几何检测器识别。它检查真实像素中的黄色区域、
双竖杆、横杆和上下空隙，支持近地裁切；不读取地图目标位置或 Gazebo 标签。
H 结果使用 `vision.marker:` 来源，与 `vision.pt:` 分开；不把桶预测改名成 H。
该规则只适用于本次地图标记，不能推广为任意 H 标记识别。原验证集也只有 8 个 H
实例，验证集指标不能代替实际场景的识别验收。

## Mission 与 Action

模板文件为 `simulation/missions/cuadc2026/rescue_2026_full_auto.json`，采用当前
schema 2 Graph、ForEach、Blackboard、实例绑定和发布机制。原始任务仅用于参数核对。

流程：估计器稳定等待 → GUIDED/Arm → 4.5 米起飞 → 5 米投放区观测、去重、选桶
→ 最多两次接近、目标重新确认、对准下降、投放、爬升 → 六点侦察
→ 返航 4 米／下降 2.5 米 → H 对准下降 → 原生 Land。

新增 `Rescue.Takeoff`、`Goto`、`CaptureView`、`FuseViews`、`SelectDropTargets`、
`ConfirmTarget`、`AlignDescend`、`ReleasePayload`、`CaptureReconView`、`LandingTarget`。
原速度切换落实为每航段 2、1、0.2 m/s 的水平速度限制。帧为明确的 odom ENU，
场地前方为 +Y，不做隐式 GPS/map 坐标转换。

主要兼容调整：

- 不沿用 continue-on-failure、无观测中心点投放或对准超时当成功。
- 一个桶接收两瓶，两个桶各一瓶；原 8/9 通道映射至 payload_1/payload_2。
  1800/1370 和 1835/1335 保留为配置标识。旧桥的 9/10 通道冲突不再存在。
- 临时失去目标立即请求零速度，最多等待 3 秒；等待期间不下降、不投放。
  接近后只允许同来源、同类别、原位置 0.4 米内唯一新鲜匹配的显式重新确认。
- 选定目标／重新确认／落地目标是最多 180 秒的目标身份计划。Action 契约显式
  声明结果有效期，原有 Action 默认仍是 3 秒；原始捕获时刻不会随复制或循环刷新。
  实际动作继续要求当前 1 秒内的视觉观测；Effect TTL、Lease、会话和代际不延长。
- 投放准入可从 256 项有界不可变观测记录核验请求中的原始观测，处理高频生产者
  更新与排队之间的竞争。最新目标、位移、速度、授权和最终写入栅栏仍单独检查。

投放通过原有 PayloadExecution、双 SEND、Lease、TTL、会话／代际及显式 Safety，
由受控 Gazebo 端口请求瓶体脱离。发布成功不等于脱离；必须观察新的独立 detached
状态。发布结果不确定保持 UNKNOWN。未加入实机 PWM、第二条 MAVLink writer、
硬件控制或远程推理服务。

## 验证与边界

实际证据保留在 `artifacts/rescue-2026-*` 中，训练与 PT 逐图推理证据在外部资源目录。
早期失败轮次也保留，没有以历史成功覆盖本轮失败。

- 真实 Gazebo world 加载、8 秒时钟推进及完整清理：PASS。
- 固定模型、真实下视相机、独立 PT 工作进程、模板编译及 SEND 关闭：PASS。
- 独立 H 像素识别、2.5 米起飞、H 对准下降、Land 落地上锁及清理：PASS。
- 完整任务第 7 轮：PASS，66 个编译节点、35 个 Action 全部成功，8/9 两次投放均为 COMPLETED，六次侦察采样完成；最终落地上锁、release_safe=true。
- 清理：FINISHED / COMPLETE，凭据销毁、端口释放、实体移除均通过。
- 完整单元回归：995 项通过；最终出生点／载荷等定向回归另有 47 项通过。
- wheel 安装后从任意工作目录加载场景、编译模板和校验固定车辆：PASS。

最终 Gazebo 独立真值为 (−0.0062, 0.0056, 0.1950) 米，同时飞控报告未解锁。
完整记录见 [验收摘要](RESCUE_2026_ACCEPTANCE.json)；主要原始证据为
`artifacts/rescue-2026-native-flight-20261105-r7/result.json` 与该会话的 `samples.jsonl`。

投放完成只表示观察到了瓶体脱离，未验证投中桶或投放命中率。坐标投影及原虚拟
相机 ey 偏移仅适用于明确的固定相机／平面组合，不是实机标定或通用导航资格。
所有实测均为本机自有 loopback 仿真；硬件只读、唯一 writer、默认关闭 SEND 与
UNCONFIRMED 停止语义继续有效。

官方接口参考：[Ultralytics 训练](https://docs.ultralytics.com/modes/train/)、
[PT 推理](https://docs.ultralytics.com/modes/predict/)、
[Gazebo DetachableJoint](https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1systems_1_1DetachableJoint.html)。
