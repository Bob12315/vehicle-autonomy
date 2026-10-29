# Gazebo 场景兼容性报告

本机 Gazebo Sim 8.15.0，ArduPilot `b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`，插件源码 `3ec51428fd43deb7b71137192ba16394b450d78e`，插件 `libArduPilotPlugin.so` 已存在。ROS 2 Jazzy 由 `scripts/with_ros2.sh` 从用户级安装加载；`ros_gz_bridge` 可见，`ros_gz_sim` 和 `ardupilot_gz_bringup` 未找到。默认 SITL bin 有 arducopter、ardurover，没有 arduplane。没有使用 sudo，也没有操作实机或旧项目。

`gz sdf -k` 需要单独的 `SDF_PATH`；单设 Gazebo 资源路径会错误报告现有 `model://` 缺失。Playpen 将两个固定版本 Fuel 模型转换为本地 URI，保留原始源。Warehouse 将九个固定版本 Fuel 模型复制到适配层，修正 table v4 同一 link 中 collision 和 visual 重名、旧 physics 下 gravity 的兼容问题，原始文件保留。`prepare_*.py` 重建适配副本；依赖下载后检查每个模型本身的许可证。解析通过并不证明纹理、碰撞、模型在 GUI 中的视觉正确性。

独立运行以 headless Gazebo、隔离 partition 和 `/stats` 采样检验时间推进，测试不含 SITL。Iris 额外取得 IMU 和场景中 `axes` 模型的 NavSat 消息及仿真时间戳；这不是机载 GPS 的验证。相机话题存在但未验证非空图像；雷达未验证。Iris 的 EGL/DRI 初始化警告和 CameraZoomPlugin 警告需要图形环境排查。各场景的出生点、车辆接地、碰撞、60 秒以后的长期稳定性及重启/重置并未全部验收；仅城市单独通过一次 reset 服务测试。

Windy 包含 5、2、0 m/s 风速配置，但本轮没有无风/有风车辆动力学对照，也未证实 ArduPilot 模型受风，因此风响应 NOT_TESTED。Zephyr 场景时间推进并不证明固定翼飞行，更不证明常规滑跑起飞。Multiagent 的上游 launch 文件已获取，但两个模型、多个 SITL、端口、System ID 和命令隔离均未验证。

Iris 框架控制采用现有 `tests.simulation.environment_probe`，独立 localhost 实例、经框架安全边界运行。首次测试收到 SITL 的 JSON 和遥测，最后报 `RuntimeError: fresh vehicle state required`，没有运动通过证据；详见 `evidence/copter-framework/summary.json`、`runtime.jsonl`、`sitl.log`、`gazebo.log`。低负载第二次复测仍为同一错误。没有绕过状态新鲜度或安全门禁。

完整测试和结果见 `GAZEBO_WORLD_TEST_MATRIX.md`；`RESOURCE_MANIFEST.md` 记录来源及许可状态。日志可能包含本地会话信息；分享前请审阅。未采集 GUI 截图，不能推断视觉质量。未发现合适的截图证据时没有生成替代图片。
