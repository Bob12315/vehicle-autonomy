# Simulation Manager API

使用原 Mission Web 后端，在同一登录会话下访问 `/simulation`。认证、CSRF、Origin、Host、请求幂等 ID 和审计均复用现有 HTTP 层。请求体必须是 JSON 对象；未知字段被拒绝。没有任意命令、路径、端口或硬件连接 API。

## 查询与会话

| 路由 / operation | 参数 | 返回 |
|---|---|---|
| `GET /api/simulation/catalog` / `simulation.catalog` | 无 | 场景数组，含 source/version/license、候选 vehicles、vehicle_support 与 launchable_vehicles、资源和限制 |
| `GET /api/simulation/sessions` / `simulation.sessions` | 无 | 历史及当前会话摘要，仅最新 sample；不携带全部轨迹历史 |
| `POST /api/simulation/create` / `simulation.create` | `scene_id`；可选 `vehicle=none`、`seed=0`、`parameters={}` | CREATED 会话，已验证参数并生成 SDF；未启动进程 |
| `POST /api/simulation/start` / `simulation.start` | `id` | 立即返回 PREPARING；异步进行真实 Gazebo/SITL 启动，轮询 sessions |
| `POST /api/simulation/stop` / `simulation.stop` | `id` | STOPPING 或终态；停止幂等，清理结果以终态报告为准 |
| `POST /api/simulation/pause`、`resume`、`reset` | `id` | 实际 WorldControl 服务确认后的会话；仅无车世界允许 |
| `POST /api/simulation/report` / `simulation.report` | `id` | 完整会话报告，可在 UI 导出 JSON |
| `POST /api/simulation/logs` / `simulation.logs` | `id`；可选 `stream=gazebo`、`offset=0`、`limit=32768` | text / next_offset；stream 仅 gazebo、sitl、sdf-check，limit≤65536 |
| `POST /api/simulation/test` / `simulation.test` | `id`；可选 `name=GetVehicleState`、`parameters={}`、`allow_send=false`、`timeout_s=30` | 原 Action Runtime 的查询结果和 Action ID；其他行为拒绝 |

车辆选择 `none` 仅启动 World。R01 / Rover、C01 / Copter、F01 / Plane 有实际后端模型组合，依赖仍须通过本机预检；其他组合因缺少受控适配被拒绝。目录中的 vehicles 是目标候选，不是实测资格。VTOL 在缺少模型/profile 时始终不可启动。

运动测试通过报告中的唯一 `target` 使用原 `/control`、Action Lab 和 Mission Studio。`simulation.test` 限为只读查询，不能绕过浏览器控制持有者或原 SEND 授权。可信服务器启动参数 `--allow-send` 才能配置管理器的部署 SEND，浏览器不能在 create 中请求部署授权。

报告含 `test_id, scene_id, scenario_id, world_id, vehicle, vehicle_id, configuration, state, created_at, started_at, ended_at, levels, metrics, samples, tests, faults, logs, cleanup, error, history`。configuration 记录有效参数、种子、版本和生成哈希；levels 的值严格为 PASS / FAIL / BLOCKED / NOT_TESTED。L1/L2 的自动结果不会自动推断 L3..L6，后者须由相应真实验收证据记录。

## 资源与软件扰动

后端 use-case 支持 `simulation.assets {}`、`simulation.asset_status {asset_id}`、`simulation.install {asset_id}`、`simulation.uninstall {asset_id}`。asset_id 只允许可信锁定清单中的标识。install / uninstall 立即返回有界后台任务，状态为 INSTALLING / UNINSTALLING，完成后通过 asset_status 的 `job` 返回 SUCCEEDED / FAILED / CANCELLED、结果或错误。相同资源操作互斥，最多两个任务；未结束的 U_ 会话保留其资源，不能同时变更。HTTP 暴露范围以当前 Web handler 的路由表为准。

故障 use-case `simulation.fault` 接受 `{id, settings}`。settings 仅允许：`delay_ms` (0..2000)、`loss` (0..1)、`freeze`、`sensor_interruption`、`command_timeout`；后三者必须是布尔。它只作用于该会话已有的 Framework 软件链路，记录准确来源；不支持对外部车辆或 SITL EKF 传感器宣称注入。故障恢复发送空 settings。GPS/IMU/barometer 等未知字段拒绝。

## 本机命令

```bash
python -m vehicle_autonomy.app.simulation.cli list
python -m vehicle_autonomy.app.simulation.cli check R01
python -m vehicle_autonomy.app.simulation.cli smoke --scene R01 \
  --data-dir artifacts/simulation/smoke-UNIQUE --seed 42 --seconds 8 --timeout 90
python -m vehicle_autonomy.app.simulation.cli batch \
  --data-dir artifacts/simulation/batch-UNIQUE --seed 42 --seconds 8 --timeout 90
python -m vehicle_autonomy.app.simulation.cli smoke --scene C01 --vehicle copter \
  --data-dir artifacts/simulation/copter-UNIQUE --seconds 10 --timeout 180
python -m vehicle_autonomy.app.simulation.cli compare \
  /absolute/baseline/report.json /absolute/candidate/report.json
```

默认 batch 仅 24 个专项编号，逐场景运行，不把缺依赖的上游条目算作已运行。可重复 `--scene` 选择子集。每场景保留独立证据及 `smoke-result.json`，总结果为 `batch-results.json`。CLI smoke 只检验 L1/L2，不会解锁、起飞或移动。固定翼运动测试必须使用原生固定翼策略，不能用 Copter 零速或悬停方法验收。

### 并发与资源保留补充

每个数据目录持有整个 Manager 生命周期的独占文件锁；第二个进程不能把仍存活的
会话当作重启恢复。启动就绪发布与取消请求串行，取消后不能重新发布 READY/RUNNING。
报告写入失败独立于进程清理；自有进程、Driver 与凭据仍执行回收。

上游场景从创建到退出保留共享资产缓存锁，阻止其他 Manager/AssetManager 删除或
替换其网格、纹理和插件依赖。缓存更新使用互斥锁，忙时返回明确错误，可在会话退出后重试。
浏览器对已被其他浏览器持有控制权的车辆执行 fault/stop，必须使用原控制 token 或先走
既有明确接管流程；管理 API 密钥也不绕过该所有权检查。

## 通用车辆组合接口（2026-10-29）

所有接口保留同一登录、CSRF、Origin、Host 和请求 ID 校验。车型、World 和出生预设来自
后端注册表，浏览器不能提交文件路径、命令、端口、System ID、二进制或 SEND 配置。

- `GET /api/simulation/vehicles`：固定定义列表；READY 只表示 SHA 锁一致，VTOL 返回
  BLOCKED 与明确原因。物理/传感器/飞控参数来源均可查看。
- `GET /api/simulation/catalog`：新增 `spawn_info`、各车型 `vehicle_support` 与静态
  准入说明。没有原生证据的组合保留 NOT_TESTED。
- `POST /api/simulation/create`：支持旧 `{scene_id,vehicle,spawn?,seed?,parameters?}`，
  或 `{scene_id,vehicles:[{kind,slot_id?,spawn?}],seed?,parameters?}`；两种车辆字段互斥，
  最多四车、空列表为仅 World。spawn 是 `{id:"center"}` / `{preset_id:"north"}`，
  或完整 `{x:0,y:3,z:0.195,heading_deg:0}`，严格校验实际支撑面与同伴间距。
- `POST /api/simulation/add_vehicle`：`{id,vehicle:{kind,slot_id?,spawn?}}`。
  已有同伴须均为安全静止地面状态；执行前按实际 Ground Truth 重验间距。
- `POST /api/simulation/remove_vehicle`：`{id,vehicle_id}`，只退役选定车。
- `POST /api/simulation/switch`：`{id,scene_id,seed?,parameters?,spawns?:{slot_id:spawn}}`。
  校验新配置后异步停止旧会话并创建全新身份；固定 profile 不变。

add/remove 返回原会话，`operation` 提供 RUNNING/SUCCEEDED/FAILED、时间和 error。
switch 返回原会话，`switch` 提供 PREPARING/STOPPING/STARTING/SUCCEEDED/FAILED、
`new_session_id`、目标场景和 error。旧报告不会被覆盖；新会话有 `previous_session_id`。
空中、仍解锁、有运动或未解决安全屏障的切换/移除明确失败，原会话在可恢复时保留运行，
须先经原控制页安全退出。运行时错误或无法确认的局部清理会退役整个 World。

会话 `vehicles[]` 包含独立 id/slot_id/target/System ID/ports/entity_name、固定版本与
fingerprint/model/parameter/sensor SHA、五个启动阶段、实际参数回读、估计状态、
独立 Ground Truth 与日志定位。`retired_vehicles[]` 保留移除记录。顶层 vehicle/target
继续作为首辆车的兼容别名，不适合在多车状态下隐式控制。

`logs`、`fault`、只读 `test` 接口新增 `vehicle_id`；多车必须明确选择。日志 stream
仍限 gazebo/sitl/sdf-check；SITL 流按所选车辆分离。查询测试继续只接受
GetVehicleState/空参数/SEND=false，运动只能进入原 `/control`、Action、Tool/Mission 流程。
World stop/switch/add 等操作检查全部相关控制页的 reservation；单车 remove/test
检查相应车。控制页须安全关闭 SEND 后释放，不能用 API bearer 绕过另一页面的所有权。

接收故障虽然只注入所选链接，当前失败清理可能结束整个共享 World，因此 fault 也检查全部车辆的控制页 reservation；须先在相关原控制页安全释放，不能间接终止另一页面保留的车辆。
