# 三车型控制扩展基线

- 起始分支：`fix/phase1-test-credential-cleanup`，工作区干净。
- 起始提交：`148a224fae4a652b8f250be827d8e79a9e41bbf9`。
- 当前独立分支：`feat/phase2-three-vehicle-control`。
- 基线单元：386 项全部通过，0 跳过，40.568 秒；原始记录
  `artifacts/phase2-control/baseline-unit.{json,log}`。
- ArduPilot 本机源码：`b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`，工作区干净。
  现有外部 SITL 只有 Rover/Copter 二进制；本任务在项目忽略目录创建独立源码副本、
  拷贝本机已安装的子模块及其 Git 元数据，禁止更新外部源码、模块、参数、构建目录或状态。
  独立 `waf configure --board sitl --no-submodule-update` 后，以
  `waf plane copter rover -j6 --no-submodule-update` 实际构建三车型，记录在
  `artifacts/phase2-control/build.log`，二进制位于
  `artifacts/phase2-control/ardupilot-source/build/sitl/bin/`。
- Gazebo Sim 8.15.0；ArduPilot Gazebo 插件源码
  `3ec51428fd43deb7b71137192ba16394b450d78e`。原 Zephyr 模型无起落架且示例初始姿态用于
  手抛/垂直放置，不能用它的起飞结果冒充滑跑。本任务另建带三自由轮、平放起点的专用模型，
  沿用上游空气动力和执行器插件，保留许可证与来源。
- Python：隔离 `.venv-migration`，3.12.3；pymavlink 2.4.49。可选 Gazebo 依赖只在显式测试加载。
- 正式源码仍为七模块；Plane 归 `vehicles/plane/`，共用 Protocol/Transport、唯一 Writer、
  Execution、Authority、World/Localization。原 Rover/Copter 参数和物理阈值文件不改。
- 原始 Phase 1 PASS/FAIL、第三轮审查及 P2 凭据销毁证据保留，不重新生成旧哈希。
  本轮证据使用 `artifacts/phase2-control/`，不覆盖以前的验收目录。
- 不连接真实车辆，不开放 hardware_controlled，不开发摄像头/雷达/SLAM/Nav2/VLM/AI 能力。

官方文档与本机源码核对、车型差异和验证合同见
[能力矩阵](CONTROL_CAPABILITY_MATRIX.md)。
