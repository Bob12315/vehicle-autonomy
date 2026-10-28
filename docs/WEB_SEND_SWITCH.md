# Vehicle Control: one SEND switch

2026-10-29 用户变更：Vehicle Control 只需点击一次 **SEND ON**，不再单独
Acquire Control，也不再逐条授权或弹出 Arm/Disarm/Takeoff/AutoLand 的确认框。
开启后，模式、目标、起飞/降落、每一段按住操控都直接由对应按钮触发。

SEND ON 不产生车辆 Action，也不自动解锁或起飞。RViz 点选仍只产生候选，操作员
点击「执行此目标」才提交既有 Goto；该点击不再附加 SEND 勾选或授权弹窗。
SEND OFF 请求停止自己的持续输入并安全退出；不等同于空中强制 Disarm。

后端沿用既有页面会话预留，只将这一步合并到 SEND ON，不再作为第二道操作流程。
仍保留浏览器登录/CSRF、明确授权的自有仿真、Mission/其他页面互斥、遥测有效性、
逐 Action 的 SEND 字段与 SafetyPolicy、Execution Lease/TTL/generation、唯一 writer、
独立输入 watchdog 和 UNCONFIRMED 栅栏。没有开放硬件发送或无条件 API。
任务占有时不能开启 SEND；须等待任务退出，或明确请求原任务安全退出。

该开关作用于当前页和当前车辆的有效连接；无需在相邻指令或每段按住运动间重新开启。
刷新、切换车辆、断线、登录失效、主动关闭后回到 SEND OFF，不自动恢复运动。
失焦/松开按键仍停止持续输入。统一登录会话不因本改动失效。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m tests.web_ui.browser_acceptance --run-dir <fresh-directory>
.venv/bin/python -m tests.web_ui.send_browser --run-dir <fresh-directory>
```

全量测试 773 passed / 120.359s。实际 Chromium/HTTP fixture 验证通过：一次 SEND ON
连续完成模式、Arm、1.5m Takeoff、两段按住/松开输入和 Land 的提交；只出现一次开启
请求，无逐条弹窗或勾选。验证三车型、关闭后按钮禁用、开关不产生 Action、断网回 OFF、
登录保持与 390–1680px 布局，零 JS 错误和零真实车辆写入。这里明确使用状态/Action
fixture，不将其宣称为本轮真实飞行验证。既有控制算法、ACK/状态确认与停止判据未修改。

原始浏览器证据在 `artifacts/rviz-v1/send-on-ui-20261029/` 和
`artifacts/rviz-v1/send-actions-20261029/`。先前真实 SITL 结果及尚未关闭的 Rover
控制风险，继续以 [RViz 集成报告](RVIZ2_VISUALIZATION_REPORT.md) 为准。

当前运行的 Copter/Gazebo/SITL/Agent/RViz 无需重启。刷新 `/control` 获取新界面，点击
SEND ON，然后操作模式、Arm、Takeoff、Land。未自动替操作员开启 SEND 或飞行。

## GUIDED 速度控制开关（2026-10-29）

多旋翼高级面板增加 **GUIDED 速度控制 ON/OFF**。它是运动模式开关，不是另一道 SEND
授权。SEND ON、已解锁、实际 GUIDED 且已经起飞时可开启；开启先创建一条零速度
SetVelocity Action，按键在同一条会话内更新目标速度。

- 按住方向键发送速度；松开或点击 HOLD 归零，持续发送零速度心跳，保持原 Action。
- 再次按下继续更新同一 Action，不重复创建/退出，不反复请求物理停止屏障。
- 关闭速度控制开关才取消 Action；确认实际安全退出后，可切模式、Land 或 RTL。
- 失焦、隐藏页面、断线、SEND OFF、车辆/认证失效仍退出；后端 0.4 秒 deadman 保留。
- 遵守现有 Action 上限，单次最多 60 秒并显示约剩余时间；到期退出，不延长后端 TTL，
  不自动重新开启。Rover 原有松开停车/HOLD 行为保持不变。

按键即时变更与周期心跳共用序列和一次性 deadline ticket，且在前次更新回复后至少间隔
60ms，避免快速按下/松开触发后端 20Hz 频率限制而意外退出。异步回复绑定原 session，
关闭或换车后旧回复不会重新激活输入。

全量测试 773 passed / 106.539s。真实 Chromium/HTTP fixture 测试证明零速度心跳跨越
deadman 时间仍维持同一 Action、松开/HOLD 后可再运动、快速切换不退出、显式 OFF
取消、更新和 stop 同时断路时后端独立超时、真实浏览器标签失焦退出且不自动重开。
布局、三车型和共享登录另行通过。证据在 `artifacts/rviz-v1/guided-toggle-v4-20261029/`
和 `guided-toggle-layout-20261029/`（最终速度专项另在 `guided-toggle-final-20261029/`）；
这里不是新的物理飞行验收。既有控制链路未改，未对操作员的飞行发送测试指令。
收尾发现原 Gazebo 自行异常退出（-4），因此保留日志并另启完整 Copter 环境；这不是
以重启替代停止确认，也没有自动 Arm/起飞。原生 Gazebo 崩溃原因尚未定位。
