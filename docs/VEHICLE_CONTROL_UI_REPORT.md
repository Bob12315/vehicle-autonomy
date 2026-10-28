# Vehicle Control UI 与统一登录交付记录

日期：2026-10-28。范围：现有 Web UI 的 Vehicle Control、必要共享认证模块及其测试。
未改动 Mission Studio 编辑器、规划算法、旧 CUADC 项目或 Tool Agent 内部架构。

## 审查结论与实现

原前端是原生 HTML/CSS/JavaScript，无 React/Vue、共享路由框架或组件库。
Dashboard、Tool Manager、Workspace 共用 `tool-console.css` 的深色侧栏、浅色内容区、
青绿色强调色、字体、边框和表单。原 `/control` 是独立通用 Action 表单并包含画布，
本轮复用 Dashboard 样式和导航，采用固定状态栏、遥测 / 控制 / 安全反馈三列，
在平板和窄屏依次折叠；无地图、点云或新三维场景。

重复输入密钥的根因是各页面分别读取自己的 `#token`，并直接构造 Bearer/CSRF
请求；导航销毁页面变量，后端没有浏览器会话。现统一在 `/login` 验证一次密钥，
所有页面使用共享 `VAFAuth`，原有前端架构保留。

后端已有 Action Runtime、Control Authority、SafetyPolicy、Vehicle Adapter、
签名 MAVLink 与唯一 writer；HTTP 状态轮询和基础控制 API 已存在，原来没有统一
浏览器遥测 WebSocket。本轮仅增加只读状态流与操作入口预约，不增加车辆命令。

| 模块 | 本轮职责 |
|---|---|
| `app/web/auth.py`、`server.py`、`action_lab.py` | 有界后端会话、登录/退出、Cookie/CSRF、页面保护、CLI 兼容 |
| `app/web/operator_control.py`、`mission_control.py` | 会话身份互斥、申请/续期/释放、明确接管、控制状态投影 |
| `app/web/live.py` | 同会话、严格 Origin、只读 RFC6455 遥测流与失效关闭 |
| `app/bootstrap/action_driver.py` | 在原车辆线程发布既有 ACK/状态证据的只读副本；HTTP 不访问端口 |
| `app/web/vehicle_display.py` | 真实字段新鲜度；过期电池和缺失字段不显示正常值 |
| `static/manual-control.html/js`、`vehicle-control.css` | 同风格三车型控制台、动态禁用、确认框、工具快捷入口 |
| `static/auth.js`、`login.*` | 共用 API client、会话恢复、登录失效跳转、跨标签退出 |
| 其他页面的 HTML/JS | 删除独立密钥框，仅接入共用认证；Studio 编辑功能不变 |
| `tests/web_ui`、`tests/browser_auth.py` 及既有浏览器入口 | HTTP/WS 安全、共享登录、布局、控制与回归 |

## 已实现的实际控制

| 车型 | 操作与语义 | 本轮真实仿真 |
|---|---|---|
| Rover | 解锁/地面上锁、GUIDED/HOLD、限速按住前后/转向、松开停车、原生 HOLD、ENU Goto、ReturnHome | 全部通过；返航误差 0.329 m |
| Copter | 解锁/地面上锁、GUIDED/LOITER、0.2–2 m 起飞、Land、Hold/LOITER、ReturnHome；折叠 FLU 速度/偏航和 ENU Goto | 全部通过；两次起飞、单独降落及 RTL 后落地上锁；返航误差 0.153 m |
| Plane | 地面 MANUAL、解锁/地面上锁、空中 GUIDED/LOITER/RTL、WGS84+AMSL 目标；折叠仿真跑道起飞/AutoLand | 全部通过；真实目标转向、盘旋、返航接近、自动着陆/滑跑和释放 |

Rover 复用已经验证的 `Drive` 接口，未将按钮直接翻译为任意 MAVLink。
Copter 连续控制复用 `SetVelocity`，坐标为 `base_link` FLU；位置目标为 `odom`
ENU，显示的实际高度与请求起飞高度分开。Plane 不提供悬停、原地转向或空中上锁。
Plane 原生目标/模式完成仅确认配置，界面明确区分物理到达，保留原来的显式续飞流程。

显示车辆身份、模式、armed、电压/电量、速度、姿态、航向、GPS、EKF flags、
高度与新鲜度；数据只来自 Driver 发布的真实遥测。缺失和过期显示未知。
当前接口没有空速和独立 failsafe 标志，因此明确显示未知；EKF flags 也不伪装成
“预解锁检查通过”。Copter 没有注册 BRAKE，本页使用已实现的 LOITER。

## 登录生命周期与权限

一次登录建立不含原密钥的随机不透明 Cookie；后端仅保存其 SHA256 索引。
Cookie 为 HttpOnly、SameSite=Strict、Path=/；HTTPS 连接或显式 `--https-origin`
部署启用 Secure。后台保存独立 CSRF nonce、身份、闲置期限 30 分钟与绝对期限
8 小时，最多 128 个有效会话，并限制失败登录频率。不信任任意 forwarded 头。
HTTP 本地开发仍绑定 loopback；本轮没有部署或宣称验证生产 TLS 代理。

Dashboard、Control、Tool Manager、Workspace、Logs、Settings、Studio 和 Action Lab
共用 Cookie。刷新通过 `/api/auth/session` 恢复，原密钥不进入 URL、日志、
localStorage/sessionStorage，也不由各组件保管。只在失效、过期、退出或后端重启
后重新登录。会话为后端进程内状态，不持久保存长期管理密钥。不同端口的独立后端
各自登录，其 Cookie 名包含端口，避免本地多实例互相覆盖。

REST Cookie 写操作由后端检查 CSRF；读写请求检查可信 Host/Origin。WebSocket
必须具有同一个有效浏览器会话和精确匹配的 Origin，不接受查询串凭据或写命令，
过期/撤销关闭连接，最多四条实时流，HTTP 轮询作为回退。连接恢复只恢复数据。
主动 Logout 撤销会话、通知其他标签页，并请求本会话人工 Action 退出。Agent 的
长期凭据仍仅供独立 Agent 通道使用，浏览器不接触，后端拒绝两类密钥相同的配置。

## 控制权与安全

Observer 只能看；Acquire Control 在后端核对会话、车型、真实自有仿真、有效遥测、
部署授权和资源空闲后建立十秒入口预约，页面每两秒续期。这不是物理 Execution
Lease，也不会打开 SEND。Manual Control 的每个动作仍经原 Action、Execution、
Vehicle、Protocol 和 Transport，检查双 SEND、SafetyPolicy、TTL、session 与 generation。
系统和 Action SEND 初始仍为 false。

Mission 正在占用时申请被拒；接管必须确认，先请求原主体安全退出，再申请控制权。
未确认安全释放时不得让后续动作取得物理控制。Arm、Disarm、Takeoff、仿真 AutoLand
需要独立确认，模式/目标操作授权一次即消耗；发送、ACK、状态确认分开显示。
每次提交重新检查遥测和控制权；后端继续执行原有更严格的实际准入。

持续运动沿用独立的约 0.4 秒输入 watchdog。松开、失焦、隐藏、断网、失去控制权
都会停止更新并请求安全停止；浏览器请求丢失时由后端超时处理。会话撤销、预约
超时或非预期车辆 epoch 改变也请求取消。浏览器换页/刷新丢失操作 nonce 后只读
恢复，旧预约最多十秒超时；不自动授权或恢复运动。UNCONFIRMED 仍阻止不安全释放。
HardwareReadOnly 保持只读，hardware_controlled 不开放。本轮没有对真实硬件发命令。

## Tool Manager 联动

控制页从实际 Agent/Registry/Workspace 上下文显示 QGroundControl、RViz2、Gazebo
的轻量入口，调用原 Tool Manager 启动/打开 API。离线、缺依赖、外部进程或未注册
时显示实际原因，不制造可操作的假入口。工具窗口在 Agent 桌面打开，不嵌入页面。
Agent 只需部署时预配置凭据与 allowlist，进程启动后自动上线、断线自动重连，
不需要每次手动登记；Web 登录不等于启动本地软件或启动 Agent。

本轮三次真实运动验收同时从实际 Tool Manager 启停/重启原生 ROS 2 观察器，
检查真实 PID、发现信息和进程退出。快捷按钮另以真实 OS 进程 fixture 验证调用链，
不把它称为原生 RViz/Gazebo 验收。本轮未重验三个原生 GUI 窗口与运动仿真并发时的
桌面时序；既有 copter-desktop 本地组合的仿真时钟问题不在本轮宣称解决的范围内。

## 测试与证据

最终数字、原始文件摘要和 SHA256 见 [机器可读索引](control-ui-evidence.json)。
所有 fixture 浏览器测试明确标注非 SITL；真实运动测试从本仓库脚本启动全新自有
ArduPilot SITL/Gazebo，经真实 Chrome UI 点击/按住键控制，HTTP 只作观测，
独立 Gazebo 真值确认物理结果。未用 Mock 代替三车型运动。

- 全量 `python -m unittest discover -s tests -v`：最终 747 项；包括原有测试和新增
  会话、权限互斥、过期、CSRF、Origin、重放身份边界、WebSocket、撤销与超时测试。
- 实际 Chromium/HTTP：三车型切换、Observer/Manual、按钮禁用、参数、关键确认、
  五个控制中心视图/Studio/Action Lab 共用登录、刷新、退出、过期、断网重连、
  1680/1280/1024/768/390 宽度；零 JavaScript 错误，fixture 零车辆写入。
- 原 Mission Studio 浏览器回归：十类节点、边编辑防护、实际 Wait Mission 执行、
  多尺寸布局、过期 Plane 禁用；零车辆写入。没有重构 Mission Studio。
- Tool Manager、Workspace、Dashboard 的真实浏览器/HTTP/Agent/进程回归通过；
  fixture 工具与原生 ROS 2 工具证据分别记录。
- Rover、Copter、Plane 真实新 UI SITL 全部通过。Copter 额外验证实际运动后的
  watchdog/blur/offline，停稳速度分别为 0.0147/0.0144/0.0054 m/s。
- 三轮均验证初始双 SEND 关闭、缺 Action SEND 拒绝、QGC 单向观察链不可写，
  退出无残留进程组、临时凭据已清除。Plane 全程保留续飞及物理安全释放语义。
- `pip check` 通过，标准隔离 wheel 构建通过，检查新增认证静态资源均进入 wheel。

开发中保留的失败记录也没有删除：Rover 第一次脚本未等待 UI 按键启用；Copter
第一次脚本使用 Playwright 隐式单页 context 无法再开标签；第二次被 Playwright
永久模拟聚焦遮蔽真实 blur。修复的是测试同步/context/焦点仿真设置，重新完整执行
后通过。最终失焦测试关闭 Playwright 聚焦模拟，实际切换标签并检查焦点丢失，
未向页面人工 dispatch blur，也未直接调用车辆端口。

## 启动和人工复测

在仓库根目录使用已有隔离环境：

```bash
./scripts/start_copter_sim.sh --headless
# 汽车改为 start_rover_sim.sh，固定翼改为 start_plane_sim.sh
```

访问多旋翼 `http://127.0.0.1:8781/control`（汽车 8780、固定翼 8782）。从终端打印的
私有文件读取密钥，在登录页输入一次；在此后端所有页面内无需重复输入。等待有效
遥测 → Acquire Control → GUIDED → 模式单次授权与实际确认 → 解锁确认 → 输入
1.5 m 并确认起飞 → 根据需要展开高级面板，每段运动重新勾选授权 → 单独 Land
或 ReturnHome，观察落地、上锁和安全释放。Ctrl+C 清理本次自有仿真。

需要原生工具时使用既有 [Tool Agent 部署](WEB_TOOL_AGENT_DEPLOYMENT.md)，不要把
Agent 密钥粘贴进浏览器。逐车型语义、只读启动和停止见
[程序启动说明](simulation/program-start.md)。自动回归入口例如：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m tests.web_ui.browser_acceptance --run-dir artifacts/control-ui-UNIQUE
.venv/bin/python -m tests.simulation.program_launch --kind rover --motion --run-dir artifacts/control-rover-UNIQUE
# 三车型原生工具/新 UI 验证：添加 --tool-registry <已配置原生 ROS2 Registry.json>
```

没有真实硬件运动验收、空速/failsafe 新数据源、生产 HTTPS 部署或新增 BRAKE/悬停能力。
界面可操作不代表这些未验证能力已经实现。Git 提交由本次最终交付消息提供。
