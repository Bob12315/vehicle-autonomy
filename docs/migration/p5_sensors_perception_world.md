# P5 Sensors / Perception / World Model 验收记录

## 当前路径与迁移边界

本阶段把现有 YOLO/RKNN 实现接到标准化 Sensor 和 Perception 边界，并建立最小 WorldSnapshot。生产飞行控制链、RK3588 RKNNLite 推理路径、默认 `executor.send_commands: false`、SEND / Action 双门禁及 stop/zero 机制未改。未实现 LiDAR driver、WebRTC Camera、RTSP 新适配器、VLM 或远端推理。

| 子项 | 已实现 | 仍保留的兼容层 |
| --- | --- | --- |
| P5-01 Sensor Contract | `contracts/sensors/` 定义只读 BGR8 `CameraFrame`、`CameraPort`、`SensorHealth`；`PointCloudFrame` 仅是未来扩展契约 | 无 LiDAR 驱动或跨进程相机协议 |
| P5-02 Camera | `VideoSourceCameraAdapter` 将现有 `VideoSource` 包装为 CameraPort；`yolo_app/main.py` 从端口读取，USB V4L2 / `/dev/video*` 路径保持 | 原 VideoSource 仍负责实际 OpenCV / GStreamer 采集；既有文件、RTSP、UDP 输入保持兼容，但未声明为新的正式 Camera adapter |
| P5-03 Pipeline | `YoloPerceptionPipeline` 组合现有 RKNN tracker 与目标管理，输出类型化 `PerceptionResult`，同时给 UDP publisher 提供旧 `CurrentTarget` / `SceneDetections` | `main.py` 继续编排命令接收、录制、MJPEG 和状态打印；UDP publisher 仍使用旧数据形状 |
| P5-04 PerceptionPort | `YoloUdpReceiver` 移入 `application/adapters/`，保留 `app.bootstrap` 导入兼容；ServiceManager 将它绑定为 `PerceptionPort`，上层 World producer 只取 typed snapshot/health。`contracts.platform.ports.PerceptionPort` 现为同一 Contract 的 re-export | 旧 Web / Action 状态展示继续通过 adapter 取得 legacy target/scene；v1 UDP 输入仍保留 |
| P5-05 World Model V1 | `contracts/core/world.py` 定义不可变 `WorldSnapshot`、pose、velocity、health、target、通用 environment reference；`world_model/` 从已标准化快照发布，不读相机/遥测设备 | 无地图、障碍物、路径规划或全能世界模型 |
| P5-06 Consumer | 候选 Core 的 SnapshotCollector 在同一采集周期发布 WorldSnapshot；Core Mission/Action 适配层优先读它，过期感知不能作为可用 target。生产 SystemRunner 发布 WorldSnapshot，Action 上下文优先取其中的车辆状态，并对过期 v2 感知失效关闭 | 生产 Action 的其余视觉/场地字段、Web 和 blackbox 仍使用旧格式投影；当前无正式 Planning runtime 可迁移 |

## 数据流和健康语义

```text
VideoSource (USB V4L2 / 既有兼容来源)
  → VideoSourceCameraAdapter → CameraFrame
  → YoloPerceptionPipeline (RKNNLite / tracking / target)
  → PerceptionResult → 既有 UDP publisher
  → YoloUdpReceiver (application adapter) → PerceptionPort
  → WorldModel → WorldSnapshot → Core Mission / Action；生产 Action 渐进投影
```

WorldSnapshot 只包含当前真实可得的 vehicle state、local/global pose、velocity、perception target、health、场地参考的通用版本/原点/航向与时间戳。感知健康必须与当前 process session 匹配，接收年龄还须不超过 2 秒；不健康时仍可保留原始快照用于诊断，但 `targets` 为空。候选 Core 的采集器将超过 2 秒的 perception frame 标为 stale。生产 Action 上下文若看到超过 2 秒未更新的 WorldSnapshot，也会关闭 `control_allowed` 并使视觉目标失效。生产 UDP adapter 继续负责会话、序列、TTL、大小限制等入站校验。

`EnvironmentReference` 是从当前 FieldReferenceSnapshot 的只读投影；比赛场地语义仍留待 P6。World Model 本身不依赖 Field、YOLO、OpenCV、MAVLink、Web 或 VehicleCommandPort，也不发送车辆命令。

现有 `PerceptionFrameSnapshot` 为兼容旧协议仍保留 `yolo_process_session_id` 存储字段；新消费者使用中性的 `process_session_id` 属性。未来 VLM / simulation adapter 只需实现 PerceptionPort 并填充标准快照，无需让 Mission/Action 解码 YOLO UDP。

## 部署和后续阶段

当前实机 YOLO 推理仍仅支持 Linux ARM64 RK3588 的 RKNNLite / `.rknn` 模型。Sensor Contract 与 WorldSnapshot 是跨部署的接口，不代表当前代码已有 x86 推理、CUDA、PyTorch、LiDAR 或 WebRTC 实现。P6 应继续抽离 CUADC Field / Environment 语义；规划器若在后续阶段落地，应注入 `WorldSnapshotPort`，避免直接读取原始 UDP、telemetry 或 camera。

## 验证

P5 新增契约测试覆盖 CameraPort 的只读帧视图、pipeline typed result、WorldSnapshot 聚合与过期 target 失效、生产 Action context 的 World 车辆投影、PerceptionPort 绑定和静态依赖边界。全量测试结果为 749 passed、3 failed；3 项失败均在 P5 前已存在，分别涉及 strict profile 行数限制、align_descend 行数限制和 goto settle time。架构边界校验、稳定核心校验和 `git diff --check` 均通过；测试不连接真实飞控或 RK3588 NPU。
