# Gazebo 场景第一轮实测矩阵

日期 2026-10-29（本机时间）。下载 PASS 仅指入口文件或多车参考文件已获取，**不代表完整资源或可用场景**。SDF PASS 是解析与入口直接网格检查，不代表所有纹理、碰撞和行为通过。Gazebo PASS 仅指无头运行到 60 秒仿真时间并检查日志；车辆列要求验证出生、接地和基本物理，因此单纯看见模型不算通过。SITL 列要求实际安全运动；框架列要求安全链实际运动。`NOT_TESTED` 不等于 FAIL，`BLOCKED` 是已确认的依赖障碍。完整原始证据位于 `simulation/world_registry/evidence/`。

| 场景 | 下载 | SDF | Gazebo | 车辆 | SITL | 框架接入 | 限制 |
|---|---|---|---|---|---|---|---|
| Rover Playpen | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | 原生世界 + 本地障碍资源适配；尚未加车、检查碰撞或行驶。 |
| Iris Runway | PASS | PASS | PASS | NOT_TESTED | FAIL | FAIL | Iris 模型及 IMU 可见；两次框架探测均因状态不新鲜失败，未起飞。EGL 警告。 |
| Zephyr Runway | PASS | PASS | PASS | NOT_TESTED | BLOCKED | BLOCKED | 未找到默认 ArduPlane 二进制；没有飞行验证。 |
| Warehouse | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | 本地复制 Fuel 模型并修复重复名称与旧重力字段；视觉和碰撞未验。 |
| 城市街区 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | Rover 无 SITL 加载 10.46 仿真秒并采到位姿（z≈-0.014 m）；接地、碰撞和道路行驶未确认；单次 reset 成功。 |
| Orchard | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | 已下载果园网格/纹理；未验证实际渲染、碰撞一致性及车辆。 |
| Windy | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | 风作用于 ArduPilot 动力学未验证；没有对照实验。 |
| Multiagent | PASS | FAIL | FAIL | NOT_TESTED | BLOCKED | BLOCKED | PASS 为 launch 参考下载；没有独立 SDF，ROS 的 ros_gz_sim 和 ardupilot_gz_bringup 包缺失，未测试多实例。 |

`Multiagent` 的 SDF/Gazebo FAIL 表示本轮未建立可独立启动的场景，不是上游 SDF 语法错误。Iris 的 SITL FAIL 表示要求的“连接并运动”组合验收失败，而非二进制启动失败。所有未运行项目都不能视为通过。七个世界入口均已下载；第八项是多车 launch 参考，并非第八个世界文件。

## 性能与证据

首个 `/stats` 样本时间是加载完成的粗略上界，包含首次话题订阅等待；平均 RTF 是仿真时间除以进程启动到最后采样的真实时间，含启动开销。CPU 为进程采样，RSS 为内存快照；负载和采样时刻不同，不宜作精确基准。`—` 为未测。GPU 只取得一次全卡快照 5%、309/4096 MiB，并非各场景专属数据。资源目录当前共约 268 MiB，包含共享缓存和重复适配副本，不能将其简单分摊为每场景独占大小。

| 场景 | 仿真秒 / 真实秒 | 平均 RTF | 首次样本秒 | 进程 CPU / RSS 快照 | 运行错误/警告 |
|---|---:|---:|---:|---|---|
| Playpen | 60.612 / 62.74 | 0.966 | 4.21 | 21.0% / 393 MiB | 无明显致命错误；车辆未测 |
| Iris | 60.371 / 114.67 | 0.526 | 6.34 | 61.3% / 764 MiB | EGL/DRI 与 CameraZoom 警告；测量期间有并发 SITL 测试 |
| Zephyr | 60.237 / 85.25 | 0.707 | 4.19 | 29.5% / 173 MiB | 无明显致命错误；无 SITL |
| Warehouse | 60.585 / 69.41 | 0.873 | 10.89 | 20.0% / 228 MiB | 无明显致命错误；纹理与碰撞未验 |
| 城市 | 60.370 / 62.49 | 0.966 | 4.22 | 6.8% / 285 MiB | 无明显致命错误；未测车辆 |
| Orchard | 60.303 / 63.23 | 0.954 | 4.72 | 10.7% / 251 MiB | 无明显致命错误；视觉与碰撞未验 |
| Windy | 60.288 / 62.38 | 0.966 | 4.18 | 6.6% / 126 MiB | 无明显致命错误；风响应未验 |
| Multiagent | — | — | — | — | 未运行 |

每场景日志与采样结果见 `evidence/<id>-*/gazebo.log`、`result.json`；SDF 输出见 `evidence/check-<id>.txt`，原始 CPU/GPU 快照见 `process-sample.txt` 和 `gpu-sample.txt`，静态资源逐文件哈希见 `asset-manifest.json`。Iris 传感器在 `iris-imu.txt`、`iris-navsat.txt`，城市 Rover 位姿在 `urban-rover-pose.txt`，城市重置在 `reset-urban-retry.txt`。首次错误服务名的超时也保留在 `reset-urban.txt`。

复现命令：`python3 simulation/world_registry/worldctl.py check <id>`；`python3 simulation/world_registry/worldctl.py smoke <id> --seconds 60 --timeout 240`。框架实测：`PYTHONPATH=src:. .venv/bin/python -m tests.simulation.environment_probe --kind copter --allow-send --run-dir <新目录>`，仅运行独立仿真。截图未采集。重新生成资源及依赖参见 `GAZEBO_WORLD_SETUP.md`。
