# 通用车辆与 World 的 Web 使用说明

本页沿用 `/simulation` 仿真中心、同一登录会话和原站点布局。浏览器不保存管理密钥；所有修改继续经过共享 `VAFAuth.api`、会话 CSRF、同源与请求身份检查。运动入口为原 `/control` 与 `/studio`，仿真中心的测试按钮只发起 `GetVehicleState`，不会授予运动权限。

## 创建组合

1. 在场景库搜索并选择 World，检查资源安装状态、来源版本、车型支持和限制。缩略图是静态示意，不是 Gazebo 截图或实时视频。
2. 从固定车辆库选择 Rover、Copter、Plane 或 VTOL。详情展示登记版本、模型/参数/传感器指纹与传感器配置。不可用的组合由后端 `vehicle_support` 决定，页面禁用并显示理由；World 变化不会修改车辆定义。
3. 选择场景预设出生点，或输入 XYZ / Heading。坐标为 World 米制坐标，Heading 为度。自定义 Z 应为该位置地面高度加固定车辆定义的 `clearance_z`；页面以登记地面高度填入起始值。地形、实际碰撞、机型限制和车间安全距离最终由后端验证，预设名称不代表任何参数下都可安全启动。
4. 使用“添加另一辆车”配置其他实例，每个 World 最多四辆。不同实例需选择分开的出生位置。可选择“仅场景”创建零车 World。
5. 设置种子、已支持的环境参数并创建会话，再点击启动。创建成功只表示配置通过创建检查；World、实体、插件、SITL 和 Framework 阶段在运行状态中分别报告。只有真实阶段结果达到后才显示就绪。

固定车辆详情中的原始模型信息用于可复现检查。不能在本页更改动力学、传感器外参、飞控参数文件、System ID 或通信端口。VTOL 如被登记为 BLOCKED，不能使用普通 Plane 代替。

## 多车查看与控制

“运行与监控”列出同一 World 的每辆车，显示独立 Vehicle ID、Framework target、System ID、端口、实体名称、固定版本、指纹及各阶段状态。选择“当前查看 / 控制的车辆”后，监控、车辆日志、只读查询测试和故障注入均携带所选 `vehicle_id`，不会因车型相同而合并为同一目标。未知数据保持未知。

“车辆控制”链接携带目标片段 `/control#<target>`，原控制页只在已登记目标中选取对应实例。SEND 仍需在原控制页显式开启，各 Action 的 SEND、Execution、SafetyPolicy、Lease、TTL、会话、generation 与唯一 MAVLink Writer 仍独立检查。多车任务可继续在原 Mission Studio 按唯一 target 配置；本轮不增加跨车任务编排器。

可在当前 World 中添加车辆，或安全移除所选车辆。单车移除请求不等同整个 World 停止；确认其阶段与清理结果，并观察其他实例的连接状态。对飞机的进程清理不能冒充落地或物理停止，原 `UNCONFIRMED` 语义保留。

日志来源可选择 World 的 Gazebo / SDF 校验，或当前车辆的 SITL。未提供的日志流由后端明确拒绝，不补造输出。报告导出保留后端原始状态与验收等级；页面可加载不代表 L3–L6 已通过。

## 受控切换 World

在“受控切换 World”中选择兼容的新 World，填写新环境参数与每个保留车辆槽位的出生点。切换保留固定 Vehicle Profile，使用新的实例身份和 epoch，旧 SEND 权限不会继承。

先在原控制页让任务安全退出、解除解锁并释放 SEND。所有影响整个 World 的操作都会检查当前 World 中全部活动车辆的控制 owner；存在任何其他控制页预留时即拒绝，管理 API 凭据也不能绕过。单车移除与查询测试在明确 `vehicle_id` 后检查所选车辆的 owner，不能引用其他 World 的 Vehicle ID。页面不会通过选另一辆车取得旧车辆的控制权。

后端切换状态通过 `switch.state` 返回 PREPARING / STOPPING / STARTING / SUCCEEDED / FAILED、`new_session_id` 和错误。页面持续显示真实进度，新会话创建后自动选中；失败会保留旧操作结果，不假定为 READY。切换过程安全性与是否允许某次切换由原会话/车辆状态决定，页面按钮可点不代表后端准入成功。

## 验证入口与证据范围

`tests/test_universal_simulation_web.py` 验证真实 HTTP 登录、CSRF/同源、固定路由、多车 owner 与管理凭据边界；这些使用离线 Driver fixtures，不能作为 Gazebo/SITL 证据。

`tests/simulation/universal_browser.py` 是实际 Chrome + 原生 Gazebo/SITL 的独立入口，会创建同一 World 的多个车辆、核对唯一身份/端口、通过原控制页选定目标、移除单车、受控切换并检查固定 Profile 与新 epoch，最后保存截图、原始报告和清理结果。显式 `--allow-send` 时才通过原控制页进行 Rover 或 Copter 运动及其他车辆隔离检查；未启用时该项为 NOT_TESTED。

```bash
.venv/bin/python -m unittest tests.test_universal_simulation_web tests.test_simulation_web -v
.venv/bin/python -m tests.simulation.universal_browser \
  --run-dir artifacts/simulation/universal-browser-UNIQUE \
  --scene-id R01 --next-scene-id R04 --kind rover --kind copter --allow-send
```

目录必须为新的名称，凭据和运行证据不提交 Git。真实执行结论以本轮测试报告的 PASS / FAIL / BLOCKED / NOT_TESTED 为准；测试代码存在不表示已经执行。外部模型兼容、VTOL 资格和未实测的 World × Vehicle 组合仍需分别记录。

接收故障虽然只注入所选链接，当前失败清理可能结束整个共享 World，因此 fault 也检查全部车辆的控制页 reservation；须先在相关原控制页安全释放，不能间接终止另一页面保留的车辆。
