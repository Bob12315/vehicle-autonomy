# SLAM 原生数据资格验证

已安装原生 SLAM Toolbox 2.8.5，在隔离的 Rover SITL + Gazebo 中接通：真实 LaserScan、
原签名链 AP EKF Odometry、显式静态外参、原时间 TF、原生地图与带协方差位姿。
没有把 Gazebo 真值送入算法；真值只用于测试预言机。

`world.mapping.slam_streams` 是只读适配器，分别发布 map、slam_pose、map_transform 的有界
引用，不发布车辆命令或第二份 odom。图像/点云源与地图位姿源分别保留 source、generation
和 calibration。map frame 有独立 map epoch，不等于 AP local origin，也不隐式转换为 NED。
地图引用最多存活 10 s，定位和变换最多 500 ms；worker 心跳独立限制为 500 ms，不能因为
静态地图有效期较长而容忍失联。旧引用撤回后，序号、源时间和映射采集时间水位仍保留。

适配器固定原生 map/pose Publisher GID，检查实际 TF participant 和端点集合。当前版本
LoopClosureAssistant 与主组件分别创建 broadcaster，属于同一原生 participant；不能把两个
端点误当成两个独立 TF authority。依据上游 2.8.5 `loop_closure_assistant.cpp` 第 51 行，
同时记录实际端点。额外 participant、源切换、时钟 epoch 变化或 map→odom 跳变会停止资格，
需要显式重新装配。TF 图身份检查本身不是 DDS 强认证。

生命周期通过公开 GetState/ChangeState 服务完成，检查前后状态；一次 transition 只发送
一次，结果丢失保持 UNKNOWN，不盲目重试。开发中观察到一次 CLI graph discovery 的
“Node not found”，没有放宽检查；改为直接使用公开服务并保存实际响应。原外部 ROS Service
结果不确定性机制和持久资源占用合同保持不变。

`simulation/phase5/slam_mapping.yaml` 仅用于限定时长的真实算法资格测试，允许静止扫描
继续匹配，以区分真实新定位采样和周期重发的 TF。不能据此声称长期 mapping graph 内存预算
或 StartMapping/SaveMap 等托管 Action 已完成；正式生命周期装配和预算仍待实现。

## 开发证据

`artifacts/phase5-world-navigation/dev-slam-7/summary.json`：

- 原生建图，24,000 以上已知栅格，独立验证四面墙；保存 PGM/YAML。
- 原生 SerializePoseGraph 产生非空 `.posegraph` 和 `.data`，记录实际哈希。
- 停止后，使用 localization 节点加载原图；新 reader source/epoch 明确准入。
- 重新匹配四面墙，继续真实采样；停止原生节点后 World 中定位失效。
- 车辆 Writer 为 0；临时认证材料销毁，进程组和端口清理。

dev-slam-1、4、5、6 的失败记录保留；2、3 的较早通过记录也保留。
当前还不是 Phase 5 完整 A–I 验收，更没有宣称 Nav2 运动闭环通过。

沿用已有的显式 opt-in Karto 栅格边界覆盖层，未修改独立 ROS/ArduPilot/Gazebo 工程。
它以当前 2.8.5 头文件和 DSO 哈希核对 ABI，测试上游边界失败、覆盖层通过；构建产物和
上游许可证留在独立 artifact 中。不重写 SLAM 算法。

依据：[SLAM Toolbox 2.8.5](https://github.com/SteveMacenski/slam_toolbox/tree/2.8.5)，
[LoopClosureAssistant](https://github.com/SteveMacenski/slam_toolbox/blob/2.8.5/src/loop_closure_assistant.cpp)。
