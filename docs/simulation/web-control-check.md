# 三机型 Web 控制复验与修复（2026-10-28）

受测入口是现有三个 `start_*_sim.sh`，固定翼仍为外部只读输入
`~/twin-fixedwing` 的双发 `twin_cessna`。测试通过控制页使用的 Bearer、CSRF、
唯一请求 ID 和 `/api/manual/*` HTTP 请求执行，未直接发送 MAVLink 或修改 Gazebo
位姿。Gazebo Oracle 只订阅独立真值，不参与生产控制。Phase 5 未接入。

| 检查 | 汽车 | 多旋翼 | 双发固定翼 |
|---|---|---|---|
| 模式 | GUIDED/HOLD | GUIDED/LOITER | MANUAL、原生 TAKEOFF/GUIDED/LOITER/RTL/AUTOLAND |
| 解锁及上锁 | 解锁→上锁→再解锁 | 解锁→上锁→再解锁 | 解锁→上锁→再解锁 |
| 前进 | 托管 Drive，真值位移≥0.5 m | 起飞后托管机体前向速度，位移≥0.5 m | 实际滑跑、离地、爬升至 50±5 m，持续前飞 |
| 转向 | 托管偏航率，实际转角≥0.4 rad | 托管偏航率，实际转角≥0.4 rad | 原生地理目标，实际航向改变≥0.5 rad |
| 停止 | 停止输入、GUIDED/HOLD下的 Stop，实际速度≤0.1 m/s | 停止输入，实际速度≤0.15 m/s | 原生 Loiter，保持飞行速度，不声称空中零速 |
| 返航 | 原生 RTL→HOLD，实际到家误差约0.30 m | 原生 RTL、实际降落并上锁，误差约0.004 m | 原生 RTL 实际接近 HOME；随后 AutoLand 实际接地、停稳、上锁 |
| 信息 | 13 个阶段快照核对 | 12 个阶段快照核对 | 10 个阶段快照核对 |

固定翼 RTL 动作成功仍只确认原生配置，不冒充已经到达/着陆。测试另外观察实际
接近 HOME，再验证原生 AutoLand。最终在起飞方向跑道约72.43 m处着陆，横向偏差
约0.064 m，保持原有80 m/15 m跑道范围、0.25 m地面高度和1 m/s停车门槛。

## 修复的问题

1. **键盘按住操控被忽略。** 勾选授权复选框后焦点仍在 `INPUT`，原逻辑把 W/A 等
   全部当作编辑输入忽略。现在仅在文本、数字、选择框等编辑区域屏蔽操控按键，
   允许在授权复选框/速度滑块聚焦时操控。真实 Chrome 保持授权框焦点，使用
   W 键前进、松开停车，并通过独立真值验证；转向仍覆盖鼠标按钮。
2. **汽车到家后刹停滑移可使“成功”位置越界。** 原路径在返航条件成立后才在
   退出阶段停车，有一轮实际最终误差约0.82 m，超过既有0.75 m门槛。现改为：
   原生 RTL 接近到0.5 m时，经原 Execution 发原生 HOLD；等待其命令确认后，
   实际报告位置在0.75 m内、速度≤0.1 m/s连续2秒才完成。最终退出仍使用原有
   独立安全屏障，不放宽最终容差，不以 ACK 代替物理到家/停车。
3. **固定翼地面可选空中模式，飞行续接需要手工复制 ID。** 界面按当前状态限制
   模式选项，并提供 MANUAL→解锁→起飞的说明；后台在 Action 预检拒绝地面导航
   模式及已解锁/空中的 MANUAL。空中下一次人工动作会把同一车辆已确认、允许
   续接的 Action ID 放入显式请求，仍须重新勾选 SEND；后台继续核对原控制主体、
   会话、恢复证据和授权，不隐式继承飞行控制权。
4. **信息只显示原始模式编码，缺少诊断。** 控制页改为车型对应的模式名称，并
   显示飞控系统 ID、定位样本延迟、地速、升降速度、电池、GPS、EKF和飞控状态
   消息；状态与控制信息取同一发布切面。过期/缺失诊断明确标注；无空速数据时
   显示未知，不由地速假造空速。“已连接/有效”仍不表示通过飞控解锁检查。
5. **汽车已在 HOLD 时再点停止会报错。** 原 Stop 使用 GUIDED 速度流前置条件，
   使松开按键后的正常 HOLD 状态反而无法调用停止。改为经同一执行链请求原生 HOLD，
   等待命令确认和动作开始后的新鲜低速样本连续2秒，不为停车先切回运动模式。
   仍使用原双 SEND、资源仲裁和独立退出屏障；不抢占仍持有控制权的其他 Action。

## 验证与边界

原始记录索引见 [复验证据](web-control-check-evidence.json)。失败原件保留在
`artifacts/simulation/web-controls-baseline/` 和 `web-controls-retest/rover/`，
未用最终 PASS 覆盖。早期固定翼信息比较直接对比了不同采样时刻，产生误报；
现同时记录 pose 样本时间，并以2 m基础偏移加地速×样本年龄检查时序一致性，
最大样本年龄仍为原有3秒。该检查不是定位精度或硬件时间认证。

全量 `python -m unittest discover -s tests -v`：**675 项通过，75.872秒**。
真实三机型 HTTP 控制、Chrome 键盘/按钮控制、固定翼续接请求序列化和响应布局
回归通过。最后两项 UI 序列化检查使用隔离模拟响应，不冒充实际飞行；实际固定翼
飞行由上述独立 HTTP/Gazebo 测试验证。

三个最终仿真及键盘测试均正常关闭，进程组无残留，临时 EEPROM、签名和 Web 令牌
已销毁，外部输入哈希保持不变。不改变双 SEND 默认值、Lease、TTL、会话/代际
围栏、唯一 Writer、HardwareReadOnly 或 UNCONFIRMED 语义。

复现（每次使用新目录）：

```bash
.venv-migration/bin/python -m tests.simulation.program_launch --kind rover --http-controls --run-dir artifacts/simulation/check-UNIQUE/rover
.venv-migration/bin/python -m tests.simulation.program_launch --kind copter --http-controls --run-dir artifacts/simulation/check-UNIQUE/copter
.venv-migration/bin/python -m tests.simulation.program_launch --kind plane --http-controls --run-dir artifacts/simulation/check-UNIQUE/plane
```
