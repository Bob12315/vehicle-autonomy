# Phase 5 实施合同与当前进度

状态：开发中，不能作为 Phase 5 完成或独立 PASS 的声明。

## 基线

实际冻结起点 `34b72b57bab7a967de403c53839916a348aaf708`，初始工作区干净。
用户确认 Phase 4 独立审查完成；当前仓库和临时目录未发现额外独立审查文书，未伪造已读到 PASS 报告。Phase 4 正式开发报告、两轮证据和 UI 修复历史保留。

本机 Ubuntu 24.04 amd64，Gazebo 8.15.0。ROS 2 不在 `/opt/ros`，现有用户前缀包含 Jazzy、SLAM Toolbox 2.8.5 和部分 Nav2 1.3.13。基线 565 单元通过。独立 ArduPilot 干净，独立 Gazebo 工程的四项旧未跟踪资源保持不变。

## 已执行的初始增量

- `contracts/streams.py`：来源、传感器、源时钟、映射后的采样时间、接收时间、generation/sequence、Frame/origin/单位/高度基准、标定、质量、协方差和有界内容引用。
- `world/model/streams.py`：每个明确注册的数据流仅保存当前引用；拒绝身份/坐标/标定/epoch 不一致、序号或源时间回退，不用新接收时间刷新旧采样；缺失、过期和不合格数据不供导航使用。回放与测试真值可以展示，不能作为实时导航证据。
- `contracts/algorithms.py` 和 `engine/providers/catalog.py`：算法能力元数据和选择；与 Phase 3 安全 ProviderRegistry 分开命名。选择不授予 SEND/Lease，不替代 Action 资源；需要运动桥的 Provider 还须匹配原固定根安全 Ledger、资源定义和无未解决作业。
- `scripts/setup_ros2_local.py --full-navigation --directory NEW_DIRECTORY`：保留原选项，新增完整依赖的隔离提取；拒绝覆盖已有前缀，不运行系统安装或 maintainer scripts。

在线 WorldSnapshot 及只读 ROS 传感器侧车已在第二个增量接通，详见 `WORLD_DATA_CONTRACT.md`。实际 Rover 场景验证四类传感器引用和 CameraInfo、AP 10 Hz 位姿、原时间 TF；传感器阶段 Writer 为 0。Nav2 控制和完整 Provider/Web/SLAM/YOLO 功能尚未完成，不能据基础合同宣称已实现。

## 后续实现约束

只有 Action Runtime 拥有车辆副作用，Nav2 不连接 Gazebo 车轮或第二个 MAVLink Writer。Nav2 原生控制器 → Velocity Smoother → Collision Monitor → 受控输入桥；最终输出以实际安装版本的接口与报文验证。不可通过给普通 ROS Topic 加 namespace 就声称完成强认证。

现有 TransformTree、RosClockBridge、WorldModel、MapStore、真实 YOLOX CPU 后端和原生 SLAM 生命周期优先复用。AP EKF odom、SLAM map 位姿和测试真值分别保留，地图坐标不能隐式变成 AP LOCAL_NED。图像/点云在进程外的有界流存储，World 只保存元数据、引用和结构化结果。

Provider 的独立外部生命周期和 Typed Effect 生命周期均须取得可信退出证据；车辆停车不能证明 ROS 作业结束，ROS Goal 成功不能代替车辆物理到达。未知占用跨重启保留，算法切换必须先安全退出并重新授权。

## 依赖与验证记录

原始证据根 `artifacts/phase5-world-navigation/`：

- `baseline/manifest.json`：准确 Git 基线、逐文件基线摘要；`baseline/unit.log` 保留 565 项原始结果。
- `ros2-jazzy/manifest.json`：APT 签名校验的隔离包清单/摘要，不改变旧 ROS 前缀；`ros2-setup.log` 保存安装过程。
- `ros2-environment.json`：实际解析前缀、包版本和 ROS 消息导入；不能用导入成功代替算法验收。
- `upstream/manifest.json`：官方 Jazzy Nav2 源码/配置、SLAM Toolbox、YOLOX 依据及内容哈希。正式配置还须核对实际安装版本。
- `contracts-tests.log`：11 项新增合同边界通过；`stage1-unit.log`：全量 576 项通过。

正式 A–I 两轮物理验收、既有阶段全回归、wheel、硬件准备、完整交付报告均尚未完成。本阶段不涉及 Phase 6 AI，也不开放实机运动。
