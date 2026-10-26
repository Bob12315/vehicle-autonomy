# Phase 4 Web 界面优化与中文节点

本次在 `0cc847df0bd46cd80744d5f19bea7c609d157375` 之后优化展示，不改变 Mission Schema、Action 标识、执行链、授权、期限或安全阈值。原 Phase 4 验收报告和历史证据保留，本次不替代完整阶段的独立审查。

## 界面变更

- 统一中文导航、连接栏、状态指示、操作分组、字体与键盘焦点样式。
- Studio 分为节点库、画布、属性；版本管理与运行授权分区，增加空画布提示、节点数、缩放比例和中文运行摘要。
- 11 种节点类型显示中文：动作执行、顺序执行、并行执行、条件判断、失败备选、故障恢复、事件触发、事件响应、等待、超时限制、有限重复。画布保留原 ID / 协议类型；JSON 的 `type/action/children` 等字段没有翻译或新增展示字段。
- 18 个内置车辆动作、参数标签、车型和状态显示中文，未知扩展标识保留原名。UNKNOWN / UNCONFIRMED 仍分别表示未知 / 未确认，不展示为成功或已停车。
- 控制中心将遥测、操作、方向键、授权和资源摘要分区；原始日志与详情折叠保留，增加速度读数和按键视觉反馈。
- 390 / 1024 / 1280 / 1680 像素宽度的布局检查通过。访问令牌不持久化到浏览器，截图遮罩令牌字段。

## 验证

| 检查 | 结果与原始证据 |
|---|---|
| 全量单元 | 565 项通过，0 跳过；`artifacts/phase4-mission/ui-refresh-validation/unit.log` |
| 两次真实 Chrome UI 冒烟 | `ui-refresh-1/`、`ui-refresh-2/` 均通过；中文节点/动作、连线、属性、撤销/重做、版本保存/加载、导入/导出、等待任务成功、SEND 默认关闭和响应式检查；无车辆连接，Writer 0 |
| 用户现有真实 Rover 的只读 UI | `ui-live-readonly-1/` 通过；签名帧、odom 航迹和中文状态可显示，无控制提交 |
| 原 Rover 真实 SITL/Gazebo Chrome 场景 | `ui-rover-real-1/` 通过；Mission SUCCEEDED 且 release_safe，真实地图目标/返航/上锁正常；松键 CANCELLED，过期及断网 TIMED_OUT；三种退出的过期运动 Writer 均 0 |
| JavaScript | 上述 Chrome 场景均无页面脚本错误；桌面/窄屏截图保留 |
| 清理 | 独立真实测试 manifest 确认凭据销毁、端口释放、无剩余进程组；用户主动打开的 Rover/Gazebo 会话按要求继续保留，退出时使用原凭据清理路径 |

证据根目录均为 `artifacts/phase4-mission/`，本次输入和主要证据摘要见 `ui-refresh-validation/index.json`。
UI 冒烟使用独立 HTTP 服务和测试 Driver，不将它称为物理运动验证；物理证据来自单独的真实 Rover 场景。本次未重新执行完整两轮三车型 A–J，原正式报告保留其准确受测 SHA。

`tests/simulation/mission_browser.py` 仅适配中文保存提示和折叠详情的展开操作，原物理、安全、Writer 断言保留。新增 UI 检查入口：

```bash
.venv-migration/bin/python -m tests.simulation.mission_ui_smoke \
  --run-dir artifacts/phase4-mission/ui-refresh-UNIQUE
```

当前服务动态读取静态资源，浏览器刷新即可加载新版，无需重启车辆或重置认证状态。
