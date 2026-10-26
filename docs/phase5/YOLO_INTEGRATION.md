# YOLO 数据、World 与 Mission（当前开发增量）

真实后端为 OpenCV DNN CPU YOLOX，复用已有推理实现，不复制神经网络算法。权重来自
OpenCV Zoo，Apache-2.0，固定 SHA-256：
`c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063`。
当前未声明 GPU、RKNN/NPU 或实机相机支持。

输入为真实 Gazebo RGB Camera 的原始有界引用。测试场景渲染公开 bus 照片板；这是二维
照片目标，不能冒充三维 bus 模型。模型真实推理取得框、类别和置信度，没有预写检测结果。
没有深度，输出明确 `world_positions_available=false`，不写入原三维 World objects。

独立 worker 保留原图 source/generation、源时间、采集时间、图像引用及其摘要；输出记录
model_id、权重版本、backend、OpenCV 版本、推理开始/结束与耗时。结果 received_at 是实际
推理完成时间，原图 received_at 独立保留。检测及 JPEG 预览绑定同一原始帧，不能把旧框叠到
另一张新图上。严格验证框范围、模型、标签、分数、帧、epoch、原采集时间及原图大小。
固定四槽存储和 256 样本性能窗口；不缓存无限图像或推理历史。

结果进入已有 WorldModel/WorldSnapshot 后，PerceptionCollector 才向原 Mission Event
接口发布。保留原图采集时间和两秒有效期；读取、推理或 heartbeat 不刷新旧事实。新建的
ObservationEvents 保持原 cursor/read 协议，按 source/profile 保留单调水位，事件队列有界；
重复帧不能重放，队列溢出明确拒绝落后的订阅，不能静默跳过。检测通知最多每源 1 Hz，
出现/消失边缘即时通知；当前对象查询不受该通知节流影响。这里的 lost 表示检测列表由
非空变空，没有宣称实现目标跟踪。

独立线程发布有界 heartbeat；推理过程不在 MAVLink、Safety 或 Web 控制周期内。断流或
过期撤回引用并发布 perception.degraded；恢复必须有新的合法原图和真实推理结果。

开发中修复了两处数据链问题：事件原先可能早于 WorldSnapshot 发布，现只消费实际快照；
只读 AP 数据入口原先等待 Mission/journal 的控制锁，现原子读取 Driver 的不可变发布 cut，
不等待 Mission 持久化，不改任何写入授权。确定性并发测试验证持锁时该只读入口仍能响应。

## 已执行的独立开发场景

- `dev-yolo-image-1`：因照片板方向和照明不合适而真实失败；证据保留。
- `dev-yolo-image-2`：修正物理场景，阈值仍为 0.5，真实 bus 置信度约 0.91。
- `dev-yolo-world-1/2/5`：开发链问题与真实故障注入未生效的失败记录保留，没有修改成通过。
- `dev-yolo-world-6`：真实 RGB → 独立 YOLO → World → Mission Event → bus 条件 → 原 Query Action；
  暂停推理进程使旧引用失效，AP 仍连接且有效，恢复后新事实再次触发 Mission；通过真实
  Gazebo 服务移走照片板，服务响应必须为 true，随后真实空检测产生 object.lost。Writer 为 0。
- `vision-final-boundaries.log`：输入篡改/时域/类别/空间误宣称拒绝，正常检测与空检测正向对照。
  连续 10,000 帧事件测试验证有界缓存、水位及溢出可见性。

以上不是两轮 Phase 5 A–I 正式验收。Provider/Action 装配、完整 Web/RViz、Nav2 控制及
旧阶段全回归仍待完成。

模型依据：[OpenCV Zoo YOLOX](https://github.com/opencv/opencv_zoo/tree/main/models/object_detection_yolox)。
原照片与许可来源记录在历史 `artifacts/simulation/vision-assets/provenance.json`，未改写原始记录。
