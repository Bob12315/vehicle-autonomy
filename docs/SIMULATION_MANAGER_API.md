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
