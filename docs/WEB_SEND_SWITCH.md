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
