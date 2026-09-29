# 原程序可复用实现迁移

**状态：分组实施，生产 owner 尚未切换。** 本轮先将 CUADC Action 实现和定义表迁入 `applications/cuadc_2026/actions/`。生产组合与离线 Mission 模板校验从新位置读取；原 `missions/common/actions/` 路径保留薄兼容导入，供仍使用旧模块路径的测试和外部调用者过渡。Action 的参数、默认值、Effect 和 Mission JSON 均未改变。

场地的模型、Profile、坐标变换、几何和纯校准计算迁入 `environments/cuadc_2026/field/`。当前 FieldService 仍管理校准会话和运行时状态，生产调用点直接使用新位置的纯模块；旧 `field.*` 模块仍作同一模块对象的兼容导入。Profile JSON、运行时数据路径和场地数值未改变。

RKNN 检测器、跟踪、目标管理、类型和 Pipeline 迁入 `perception/yolo_rknn/`；`yolo_app/main.py` 继续负责当前进程的相机、UDP、录制与 Web 预览组装。旧 `yolo_app` 模块路径保留兼容导入。推理仍只使用 RK3588 的 RKNNLite / `.rknn`，没有增加 x86、CUDA 或 PyTorch 推理路径。

VideoSource、CameraPort adapter、UDP GStreamer helper 与原始 `FramePacket` 迁入 `sensors/camera/`。Perception 对旧 `FramePacket` 的导出保持同一类型对象；`yolo_app` 两种启动形式和 helper 直接脚本入口均通过导入/帮助检查。真实 USB/UDP 摄像头仍需设备环境验收。

迁移回归时还修正了两项长期存在的验收差异：`rk3588-real` Profile 缩为 19 行，渲染后的配置散列保持一致；`goto_waypoint` 生命周期测试现在验证当前定义中的 1 秒 settle 后完成，不改 Action 默认值或 Mission 参数。全量离线测试现为 `769 passed`，架构边界与 Stable Core 普通检查通过。严格生产切换检查仍有阻塞项。

后续每组遵循同一门禁：新 owner 持有唯一实现，生产调用方使用新路径，离线回归核对行为，旧路径无代码/测试/工具调用方后再删除。不能因文件已搬迁就认定旧 Runtime 可删。生产 Mission/Action owner、飞控和服务器验证仍另行处理。
