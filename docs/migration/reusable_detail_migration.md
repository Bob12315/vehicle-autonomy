# 原程序可复用实现迁移

**状态：可复用实现已按 owner 搬迁；生产 Mission/Action owner 尚未切换。** CUADC Action 实现和定义表位于 `applications/cuadc_2026/actions/`。生产组合与离线 Mission 模板校验从新位置读取；旧 Action 兼容模块在迁移仓库内调用方后已删除。Action 的参数、默认值、Effect 和 Mission JSON 均未改变。

场地的模型、Profile、坐标变换、几何和纯校准计算迁入 `environments/cuadc_2026/field/`。当前 FieldService 仍管理校准会话和运行时状态，生产调用点直接使用新位置的纯模块；旧 `field/` 源码已在调用方切换后删除。Profile JSON、运行时数据路径和场地数值未改变。

运行时场地层进一步拆分：`_reference_store`、Profile 仓库与目标解析归 Environment；`FieldService`、校准会话/事务和 Action 上下文归 CUADC Application。默认 Profile 搜索路径仍指向仓库下的 `config/field_profiles` 与 `runtime/field_profiles`，Web 和生产 Runner 已改用新 owner。

RKNN 检测器、跟踪、目标管理、类型和 Pipeline 迁入 `perception/yolo_rknn/`；`yolo_app/main.py` 继续负责当前进程的相机、UDP、录制与 Web 预览组装。旧 `yolo_app` 实现模块已在调用方切换后删除。推理仍只使用 RK3588 的 RKNNLite / `.rknn`，没有增加 x86、CUDA 或 PyTorch 推理路径。

VideoSource、CameraPort adapter、UDP GStreamer helper 与原始 `FramePacket` 迁入 `sensors/camera/`。Perception 对旧 `FramePacket` 的导出保持同一类型对象；`yolo_app` 两种启动形式和 helper 直接脚本入口均通过导入/帮助检查。真实 USB/UDP 摄像头仍需设备环境验收。

目标、机体和云台观测的融合模型、规则及 `FusionManager` 迁入 `perception/fusion/`。生产 bootstrap、应用状态与诊断工具已切换导入，旧顶层 `fusion/` 实现删除；融合计算和输出类型不变。

依赖 CUADC 场地坐标工具的 GPS 派生 ENU 融合迁入 `applications/cuadc_2026/`；Action 与测试切换导入。通用 `guidance/` 保留不依赖比赛场地的投影及融合算法。

迁移回归时还修正了两项长期存在的验收差异：`rk3588-real` Profile 缩为 19 行，渲染后的配置散列保持一致；`goto_waypoint` 生命周期测试现在验证当前定义中的 1 秒 settle 后完成，不改 Action 默认值或 Mission 参数。全量离线测试现为 `769 passed`，架构边界与 Stable Core 普通检查通过。严格生产切换检查仍有阻塞项。

Action Registry 随注册项保存定义，旧 ActionRunner 不再读取 CUADC 全局定义表；候选 Core Catalog 要求组合入口显式传入定义。仓库内调用方已切换后，删除了旧 Action、Field、YOLO 实现的兼容文件和多旋翼 Action 旧导入。全量 `769 passed`。这不代表旧 Mission/Action Runtime 可删：生产入口仍由 `SystemRunner` 驱动，候选 Core 的完整生产装配、安全出口和 Web 用例切换仍需单独验证。飞控和服务器真实场景也未接入。

进一步删除了仅转发导入的 `application.vehicle_composition`、`execution.translators`、`telemetry_link.telemetry_parser` 与 `telemetry_link.mavlink_state_adapter`；调用方现直接使用 CUADC composition、多旋翼翻译/状态模块。Typed EffectDispatcher 必须由组合入口注入车辆翻译器，不再隐式选多旋翼。全量回归保持 `769 passed`。
