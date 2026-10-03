# P10 Online Localization / Transform / WorldModel

状态：**P10 PASS**。基线 P9 `c80a18b`；日期 2026-10-03。

冻结组合：车辆自报局部 ENU `odom` 与车体 FLU `base_link`。ReportedPoseLocalization 独立投影车辆状态；同一 publication cut 的 Localization revision 与 VehicleState revision 一致，WorldSnapshot 保留 VehicleState、Localization、Transform dependencies。reported pose 将 base_link 点映射到 odom；反向查询使用逆变换，不加入未经标定的 map/Gazebo world 边。Localization 不是真值或独立融合器。

每个 reconnect 创建新 WorldModel、OnlineLocalization/Transform epoch。源 boot 时间按已有 speed-one SITL 映射到 host monotonic；`source_time` 日志保存 capture、receive、clock domain，`state_cut` 保存 publish 和同源版本。未来/过期/异域输入不采用定位；源时钟逆序沿用车辆 fail-closed 路径。动态树只插值、无外推，每条边最多 1024 样本。组合遥测保守时间戳相同但位姿更新时建立新 Transform cut，不能悄悄覆写旧历史。

`ctl status` 显示定位质量、producer、frame、采样年龄、源 revision、transform epoch 与自报位置。状态链不读 Gazebo；Oracle 继续由测试单独订阅。

相关单元：`python -m unittest tests.test_online_localization tests.test_simulation_runtime tests.test_application_runtime tests.test_transform tests.test_p2_state_chain -q`。覆盖同版切片、逆变换、跨域/未来/过期、缺失路径、拒绝外推、重连隔离及有界历史。

物理回归：`./scripts/test_simulation_v1.sh --build-dir artifacts/simulation/suite-e8ba09fa/build`，保留两车正式 App 状态/定位查询和原 +X/+Y/旋转/Stop/重连/故障物理场景；数值门槛未修改。

最终报告：`artifacts/simulation/suite-0fdc15bf/summary.json`，139 单元测试、13 阶段、7 场景全 PASS，无失败或跳过；进程组/端口清理通过。Copter/Rover 正常运动分别记录 1072/1171 个同源 cut，最大采样年龄 139.6/71.3 ms；fault 场景均通过。

后续记录图像 CPU 负载揭示 GPS fix 原用 receive，global pose 用 source boot，超过原 500 ms 配对门槛时拒绝 origin。只读审查 ArduPilot libraries/AP_GPS/AP_GPS.cpp:1405 确认 GPS_RAW_INT time_usec 是 last_fix_time_ms 乘 1000；将其纳入同一 boot epoch，未知、零、Unix stamp 不采用，GPS 不用于首次 anchor。重复、延迟、回退测试及视觉业务、对象丢失恢复场景通过。未放宽状态年龄或原点匹配门槛。
