# 基础自主系统实施完成审计

> 本文保留 P9–P17 的历史范围和测试数。最新 P21–P25 完成范围、260 项单元测试及最终装配 13 项物理门槛见 [自主导航完成审计](navigation-completion-audit.md)；本次不把历史整车全套称为重新执行。

核对日期：2026-10-04（Asia/Ulaanbaatar；报告时间为 UTC）。范围依据 [实施计划](../basic_autonomy_implementation_plan.md)。**P9–P15 localhost SITL/Gazebo 范围 PASS；P17 记录图像/CPU YOLOX/虚拟标定的软件范围 PASS；P16 真实硬件暂缓。** 基础自主闭环、非视觉业务与视觉输入替换均从正式 App 入口执行。真实飞行、现场相机标定、比赛桶模型、物理载荷、RKNN、Web/server、Planning/LLM/Agent 不在完成声明中。

## 阶段产物与提交

| 阶段 | 产物 / 验收结论 | 实现提交 | 证据 |
| --- | --- | --- | --- |
| P9 | 本机长运行 App、有限 IPC、身份/授权/结果链、两车进程 PASS | `c80a18b` | [P9](phase-9.md) |
| P10 | 遥测 Localization、同源 Transform/World cut、重连 epoch PASS | `9cc584c` | [P10](phase-10.md) |
| P11 | 不可变 Environment、命名点/区域/围栏、原点证据 PASS | `2674d61` | [P11](phase-11.md) |
| P12 | 有限基本 Action、ACK+状态/物理结果、Stop/退出屏障 PASS | `951e94e` | [P12](phase-12.md) |
| 独立合同 | 非车辆 ReleasePayloadEffect/Envelope/受控端口；车辆执行仍拒绝载荷 | `ca4df82` | [合同审查](payload_contract_extension.md) |
| P13 | 双车 basic_route 各连续两次；取消/过期/重连只读 PASS | `ad9a5fa` | [P13](phase-13.md) |
| P14 | 显式可替换仿真对象 Observation、来源/时钟/失效 PASS | `13ae576` | [P14](phase-14.md) |
| P15 | CUADC 观察驱动业务、专属仿真载荷、Rover inspection PASS | `fd1113f` | [P15](phase-15.md) |
| P16 | 未启动、未连接真实设备 | 无实现提交 | [暂缓记录](phase-16.md) |
| P17 | 实际 CPU YOLOX、记录帧/虚拟投影、正式业务及视觉故障 PASS | `9fea83e` | [P17](phase-17.md) |

阶段验证暴露的问题另行修正并提交：`ea97b9c` 为 Gazebo SIM/REAL 成对 capture 映射，`a1880f9` 为 GPS fix 源 boot 时间，`0afe6be` 为取消时立即隔离尚未发送队列。所有提交只在本地，没有 push。

## 完整回归与最终补强

最终完整报告：`artifacts/simulation/suite-3501a226/summary.json`。**29 个阶段、21 个场景全部 PASS，0 失败、0 核心跳过、0 未运行。** 该次单元 gate 为 173 项、0 失败/错误/跳过；取消队列与传感器关闭补强后的 `final-unit.json` 为 **177 项，0 失败/错误/跳过**。不能将两个报告的测试数互换。

21 场景为：两车 application、两车 environment、两车 actions、两车 route（各两次）、两车 mission_faults、objects、cuadc_first、cuadc_second、rover_inspection、business_faults、visual_business，以及原 copter_full、copter_land、rover_full、copter_faults、rover_faults。所有实际场景 manifest 均有端口释放且 remaining_process_groups=[]。

完整套件运行时还在做后续合同/关闭补强，其 framework_sha 为启动时 `ea97b9c`，工作树非空；各场景独立 manifest 记录实际启动 Git SHA、root_source_sha256 和 dirty 标志。此审计不将所有场景描述为同一个最终提交的逐字构建。最终补强后另行验证：

| 验证 | 报告路径（artifacts/simulation/ 下） | 结果 |
| --- | --- | --- |
| 最终全部单元/合同 | `suite-3501a226/final-unit.json` | 177 PASS，0 失败/错误/跳过 |
| 最终视觉业务正常链 | `autonomy-copter-a584ef0a/summary.json` | CPU 检测→世界对象→接近/Stop→仿真投放→HOME→Land/Disarm PASS |
| 视觉取消/损坏过期 | `vision-faults-7c8b79f6/summary.json` | 两种情况均 Stop 确认、撤权、无投放，显式 recovery 落地上锁 PASS |
| 实际 YOLOX 离线 | `suite-3501a226/vision_inference/summary.json` | 5 正例/2 空白，fixture precision/recall=1，0 误检；最大投影误差 0.0759 m / 延迟 464.5 ms |

完整回归使用初次自有构建 `suite-e8ba09fa/build`，重新 configure/增量 build，并非新的空输出目录构建。ArduPilot SHA `b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`；Gazebo plugin SHA `3ec51428fd43deb7b71137192ba16394b450d78e`；Gazebo Sim 8.15.0。每场景为新 world/state、独立 loopback partition 和空闲匹配 TCP/JSON 端口，清理只操作记录 start_ticks/PGID 的自有进程。

## 复现命令

在仓库根目录、具备 [仿真依赖](../simulation/README.md) 的本机执行：

```bash
python -m pip install -r requirements-vision.txt
python scripts/prepare_vision_fixture.py
./scripts/test_simulation_v1.sh --build-dir artifacts/simulation/suite-e8ba09fa/build --timeout 3600
python -m tests.simulation.harness --unit-report artifacts/simulation/final-unit-new.json
export VAF_SIMULATION_SITL_BIN_DIR="$PWD/artifacts/simulation/suite-e8ba09fa/build/ardupilot/sitl/bin"
export VAF_SIMULATION_PLUGIN_DIR="$PWD/artifacts/simulation/suite-e8ba09fa/build/gazebo-plugin"
python -m tests.simulation.vision_faults --allow-send
```

不传 --build-dir 的一键套件会在新 run 的 build 目录从空输出构建。公开 App 支持 run/ctl status/start/cancel/shutdown，只允许注册任务；启动与发送必须显式 loopback profile/--allow-send。默认 `python -m app.main status` 仍为 unwired/发送关闭，不连接车辆。仿真载荷和两种对象源必须显式加载。

## 原门槛与安全合同

原导航真值误差≤0.75 m、导航≤45 s、Stop≤8 s且稳定2 s、Copter/Rover Stop 真值速度≤0.15/0.10 m/s 均保留；原基础物理/故障场景未删除、未 skip/xfail。Rover 内部反馈到达余量 0.45 m 和阻尼只使动作在既有门槛内停止；没有提高验收容差。载荷对准≤0.3 m、目标≤1 s、速度≤0.15 m/s；车辆新鲜度沿用已有 profile 3 s，没有以视觉负载放宽原点 500 ms 配对门槛。

系统 SEND 与 Action SEND 默认 false，每步 scoped lease；Execution 在唯一 writer/载荷 mutation 前复核 session、generation、期限、租约和显式 Safety。Action/Mission 只读 Snapshot、发 Typed Effect，没有命令端口或 Gazebo Oracle。停止成功必须后续新鲜状态和独立物理证据；断链仍 UNCONFIRMED，重连不恢复旧授权/命令。取消未发送请求可以阻止副作用，已发送 one-shot 不声称撤回。

P15 载荷是独立仿真库存及位置标记，没有 Servo/PWM、弹道或真实投放；ACK 不是完成，必须另有新鲜载荷 WorldObject 和一致状态。P17 输入是 checksum-pinned 公开图像实际推理，空间位置只在显式虚拟平面标定下成立；COCO bus→bucket_1 只验证输入替换，无法外推比赛目标/真实场景精度。

## 失败记录、旧源和范围

保留失败日志，没有将失败报告改绿：P9 的 `suite-e8ba09fa` CLI 参数解析；P11 原点未就绪/早期 Rover HOME；P12/P13 Rover 控制与历史结果查询 O(n²) 周期超时；P15 `autonomy-copter-90838672` 的慢仿真对象 capture 老化；P17 早期 GPS/global 源时间配对拒绝。对应修正及复跑见各阶段审计，未降低数值保护或自动重试非幂等动作。

只读迁移审查见 [CUADC 候选清单](cuadc_candidate_inventory.md)。外部 `/home/level6/uav_ws/cuadc2026/` 的六个候选及归档中的六个候选 SHA256 与初始清单完全一致，`legacy/` 无工作树差异；没有运行旧测试/旧应用，也没有从根包导入旧运行时。新业务按依赖和安全行为审查后重写。

已完成计划授权的所有可执行软件范围。P16 按计划保持暂缓；真实设备/现场相机/标定/专用模型/RKNN/物理载荷仍需独立设备与数据证据，不继承此次仿真 PASS。
