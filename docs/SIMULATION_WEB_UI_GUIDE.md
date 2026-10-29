# 仿真中心 Web 使用指南

> 2026-10-29 通用车辆组合阶段已继续更新。当前固定模型、多车、跨 World 和原生/Web 验收以 [通用仿真报告](UNIVERSAL_SIMULATION_TEST_REPORT.md) 为准；本页旧轮次数字保留为历史证据。
仿真中心位于现有 Mission/Console 后端的 `/simulation`。车辆总览、车辆控制和任务编排侧栏均提供入口；继续使用 `/login` 的 HttpOnly 浏览器会话和原 CSRF 防护。页面不保存访问密钥，也不接收 Shell 命令、可执行参数或主机文件路径。

## 启动与操作

按现有方式启动 `vehicle-autonomy-missions` 或 `vehicle-autonomy-console`：

```bash
vehicle-autonomy-missions --port 8780 --token-file /absolute/private/web.private \
  --data-dir /absolute/private/mission-state
```

登录后打开 `/simulation`。场景库可按类别、编号、名称、来源和标签搜索。选中场景后显示来源、许可、地图范围、固定出生点、推荐测试与已知限制。缩略图是明确标注的**场景示意**；不是实际截图或实时三维画面。

选择车辆和随机种子，配置障碍物数量、风速/风向、光照与地面摩擦，点击“创建仿真会话”，再点击“启动”。默认“仅场景”不启动飞控。可选车型由后端逐场景适配白名单决定，未适配组合禁用；标记候选车型不代表已验收。

“运行与监控”每 2.5 秒读取真实会话状态。启动异步进行，错误保留在会话记录。停止会清理本次后端创建的进程。暂停、继续、重置仅用于无车环境，带飞控会话须使用原控制链；页面据后端状态启用按钮。

## 车辆、任务与安全

环境启动不授权车辆运动，双 SEND 与原 Safety/Execution/Authority/唯一 Writer 继续生效。后端允许并成功装配的 SITL 车辆可打开现有车辆控制、任务编排界面；“运行状态查询测试”通过原 Action Runtime 调用只读 `GetVehicleState`。该查询成功不代表 L4/L5 运动验收。

没有真实数据时，GPS/EKF、姿态、传感器和任务状态显示“未知”。本页不伪造摄像头流，不添加第二套地图导航；空间可视化仍由现有 RViz2 工具承担。出生点/传感器配置沿用登记模型；本页目前不更改传感器噪声和飞控融合。带飞控会话可在“软件链路故障注入”配置接收延迟、丢包、冻结、中断与发送前超时；生效点是 Framework 软件链路，明确不等同 GPS/IMU/气压计故障。清除故障不会恢复旧权限或重放排队指令。

## 报告和日志

上游场景详情提供异步“安装 / 校验资源”、“卸载缓存”和状态查询。浏览器只提交锁定的资产编号；后台最多两个安装任务，并展示实际依赖检查结果。下载入口成功不能代替完整模型/纹理/插件就绪。

每个会话可读取后端报告，分别展示 L1–L6 的 PASS / FAIL / BLOCKED / NOT_TESTED。选择另一会话可比较相同指标；未采集值为未知。导出 JSON 从当前真实报告生成。日志只能读取所选会话的有界日志，不能读取任意主机文件。

报告将实际采集的 Ground Truth 和飞控估计轨迹分别绘制，并保留各自参考系；缺失或不足两个采样点时显示无足够数据，不推定两种坐标已经对齐。暂停或重置环境不能清除历史失败、运动不确定性或提升验收等级。

## 验证范围

`tests/test_simulation_web.py` 使用真实本机 HTTP 服务验证统一登录、CSRF/Origin、操作路由、会话创建、参数边界、日志 ID 边界及幂等请求。`tests/simulation/center_browser.py` 提供真实 Chrome 点击的无车环境生命周期验收入口（`--base`、`--token-file`、`--run-dir`），保留截图、HTTP 状态与页面错误。这些是 HTTP 集成测试，不能替代真实 Gazebo/SITL 的 L2–L6 验收。实际浏览器和仿真证据以 `SIMULATION_TEST_REPORT.md` 为准。

## 本轮实际浏览器证据（2026-10-29）

`artifacts/simulation-center/browser-world-r2/result.json`：R01无车场景真实Chrome+Gazebo启动、暂停/继续/重置、日志、报告导出、停止清理及共享登录导航均PASS；零JavaScript错误。原始截图01–04与报告JSON同目录。此结果仅代表无车环境的网页生命周期，不包含SITL运动验收。

`artifacts/simulation-center/browser-assets-r2/result.json`：锁定官方air-pressure资产通过真实Chrome卸载、重新安装及状态查询，零JavaScript错误。首次资产脚本因中文翻译后的提示断言不匹配失败；原件位于browser-assets。首次world脚本暴露忙碌请求提示与测试过早操作问题；修复后重跑，失败原件位于browser-world-r1。

## Rover Goto 的停车模式

本轮实测复现了原有 Goto 退出停车确认超时。标准 Rover Goto 现在先清零原速度流，
再经原 Action/Execution 请求原生 HOLD；只有原停车确认、实际稳定窗和模式确认都满足
才完成。没有放宽停止阈值或超时。Goto 后保持 HOLD；下一次 Goto/Drive 前请显式
选择 GUIDED。编排连续多个 Goto 的自定义 Mission 时，也应在后续运动前加入
SetMode(GUIDED)。原生 ReturnHome 可以从 HOLD 开始，已重新验证。
