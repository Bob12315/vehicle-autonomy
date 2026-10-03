# P17 记录图像 / CPU YOLOX 感知替换

状态：**PASS，限记录图像与虚拟标定的软件范围**。完成核对：2026-10-04。前置 P15 `fd1113f`，独立 GPS 源时间修正 `a1880f9`、取消队列补强 `0afe6be`。实现提交见 [完成审计](completion-audit.md)。

## 输入、几何与控制边界

`sensors/camera/recorded.py` 只读普通 JSON 清单与普通图像文件，有限时间线最多 2000 帧、严格递增 PTS、模型/图像 SHA256、明确类映射和来源。不会打开 VideoCapture、相机设备或串口。按 host monotonic epoch 回放源 PTS，capture UTC 与其相关；健康记录 capture、帧接收、推理结束、延迟、丢帧、置信度、EOS、来源/校准版本和曝光来源。fixture 为瞬时虚拟曝光（0 ns），原照片真实曝光未知。

有界异步 worker 只保留最新待处理帧和输出，CPU OpenCV DNN YOLOX 实际推理。结果超过 1 s 为 INVALID，保留原 capture 年龄；漏检/同类多目标无法唯一定位时不采用旧目标，已知目标产 UNAVAILABLE，EOS 后自然过期。图像校验失败留明确健康错误，不能刷新旧目标年龄。重连生成新的 source/world epoch。

`perception/vision/projection.py` 校验分辨率、内参、显式 camera→odom 刚体变换、平面和最大距离，用检测框下沿中点射线与已知平面求交。错误 Frame 或无效标定配置拒绝加载；缺标定、分辨率不符、越界、朝上/水平/超距射线或歧义只保留 camera_optical 像素检测，不向运动 WorldModel 发布位置。普通像素标签不能触发 Goto。

正式 App 通过 `--recorded-vision-config` 替换 `--sim-sensor-config`，二者互斥；Action/Mission 和受控载荷执行器不因传感器改变。所有导航和投放仍经原授权/Safety/租约/最终写前复核。shutdown 先收束车辆/撤权，再关闭视觉 worker；worker 关闭失败不能阻止车辆隔离，状态记录 shutdown_error、进程非零退出。

## 可复现数据与限制

`scripts/prepare_vision_fixture.py` 下载 OpenCV Zoo 的 `object_detection_yolox_2022nov.onnx` 与 Ultralytics assets 的 bus.jpg，缓存到忽略的 artifacts。来源 URL、权重/照片 SHA256 和人工标注保存在 provenance.json；模型/照片校验失败直接失败，不替换版本求绿。已验收后端为 **OpenCV 5.0.0 / CPU**，没有 Torch、RKNN 或板卡支持声明。

模型 SHA：`c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063`。照片 SHA：`c02019c4979c191eb739ddd944445ef408dad5679acab6fd520ef9d434bfbc63`。照片分辨率 810×1080，人工框 `[10,230,800,725]`，接触像素 `(405,725)`。虚拟固定俯视相机 xyz=(2,1.2,3)、fx=fy=600、cx=405、cy=540、平面 z=0.05，独立人工几何目标为 `(2,0.290416666666667,0.05)`。

真实公交车照片在这里是虚拟平面纹理，COCO bus→bucket_1 是**显式 fixture 映射**。它不验证照片中的真实街道尺度、比赛桶识别或机载相机外参。回放 500 帧、2 Hz、250 s 是有限合成记录时间线，不声称真实视频或现场曝光。Gazebo 目标位置来自人工标注，业务 Action 只取检测器标准 Observation，测试 Oracle 独立裁判。

## 测试命令与结果

```bash
python -m pip install -r requirements-vision.txt
python scripts/prepare_vision_fixture.py
python -m unittest tests.test_recorded_camera tests.test_vision_geometry tests.test_application_runtime -q
python -m tests.simulation.vision_inference --run-dir artifacts/simulation/vision-offline-new
```

依赖在此次环境中已可用，没有为获取绿色报告伪造模型输出。离线验收用原图、亮度降低/提高、模糊、固定种子噪声共 5 张正例，另有 2 张空白负例。`suite-3501a226/vision_inference/summary.json`：7 帧全部通过，本 fixture precision=recall=1、0 误检、IoU 最低 0.9401、虚拟投影误差最大 0.0759 m、推理最大 464.5 ms。门槛保持 IoU≥0.8、投影误差≤0.1 m、延迟≤1 s。这组有限样本不代表一般检测精度。

设置自有构建路径后，从公开 CLI 运行正常和故障场景：

```bash
export VAF_SIMULATION_SITL_BIN_DIR="$PWD/artifacts/simulation/suite-e8ba09fa/build/ardupilot/sitl/bin"
export VAF_SIMULATION_PLUGIN_DIR="$PWD/artifacts/simulation/suite-e8ba09fa/build/gazebo-plugin"
python -m tests.simulation.autonomy_process --kind copter --allow-send \
  --mission cuadc_demo --vision-config artifacts/simulation/vision-assets/recording.json
python -m tests.simulation.vision_faults --allow-send
```

完整回归 `suite-3501a226`：29 阶段、21 场景全部 PASS，包括非视觉业务两次、Rover inspection、业务目标丢失和 visual_business。最后源元数据/关闭顺序补强后，单独视觉正常重跑 `autonomy-copter-a584ef0a` PASS，原导航/Stop/对准/落地误差门槛保留；投放须结果、库存和 WorldObject 一致，消耗后再启动拒绝。

额外正式进程故障 `vision-faults-7c8b79f6` PASS：接近中取消完成 Stop；仅原子损坏测试自有图像，使校验失败、旧目标过期、任务 `target_lost_or_expired`，随后 Stop COMPLETED、Gazebo 速度≤0.15 m/s、双 SEND 关闭且没有投放；显式 safe_recovery 落地上锁。两者均从 App ctl 触发，不使用私有车辆命令。manifest 确认端口释放、剩余进程组为空。

最终根目录单元/合同测试 `suite-3501a226/final-unit.json`：177 项，0 失败、0 错误、0 跳过，包括晚推理保留 capture/INVALID、未定位不入运动世界、PTS 回退、几何拒绝、sensor-close 异常仍隔离车辆以及共享 Mission/载荷错误路径。

保留首次 origin 证据拒绝 `autonomy-copter-019e7a78` / `autonomy-copter-9d661935`；定位健康但 GPS fix 的 receive 与 global source boot 配对偏差导致预检拒绝，未放宽原 500 ms 门槛，修正 GPS 源时间后通过，见 [P10](phase-10.md)。未将这些失败报告改成 PASS。

真实相机设备采集、实测标定、比赛数据集/专用模型、现场精度、RKNN、真实载荷和 P16 硬件仍未验收。此次完成计划允许的记录数据路径，Planning/LLM/Agent 另立阶段。
