# Sensors、Perception、Localization、Mapping

**状态：Frozen Target Architecture。** 目录与实现规划不表示当前所有设备和算法已支持。

Sensor Adapter 只负责设备连接、采集、时间戳、frame、device health 与原始数据标准化。目标类别包括 Camera、LiDAR、Radar、GPS、IMU、Depth Camera 和未来传感器。Sensor 不负责任务、避障策略或驾驶决策。

Camera 是 Sensor；视频是 Camera 的一种输出形式，不建立平级 `video/` 模块。USB Camera、WebRTC Camera、RTSP Camera、Simulation Camera、Video File 都应经 CameraPort 产出统一 `CameraFrame`。Perception 不以视频来源区分业务行为。

Perception 将 Sensor 数据转为结构化 Observation：`CameraFrame → ObjectDetection[]`，`PointCloudFrame → Obstacle[]`，或 Camera + LiDAR → `TrackedObject[]`。目标子域包括 detection、tracking、segmentation、depth、obstacle、fusion。Perception 不能直接控制 Vehicle。

Localization 负责 pose、velocity、orientation、localization quality 和 reference frame；候选实现包括 GPS、VIO、LiDAR SLAM、fusion、state estimation。Mapping 负责 occupancy、pointcloud、semantic、terrain 等世界空间表示。两者向 World Model 提供状态与空间信息，不承担 Mission Runtime 或硬件命令职责。

```text
Physical Sensor → Sensor Adapter → CameraFrame / PointCloudFrame / other data
                                         │
                                         ▼
                     Perception / Localization / Mapping
                                         │
                                         ▼
                               World Model
```

当前 YOLO/RKNN 是一个具体 Perception implementation，RK3588 是其当前 Compute Profile；它们不是框架对所有 Perception 的要求。见[当前状态](../migration/current_state.md)。
