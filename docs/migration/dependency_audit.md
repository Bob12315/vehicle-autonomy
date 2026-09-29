# P1-02 依赖审计

**状态：P1 历史静态审计；证据链接已指向搬迁后的实现。** 依据 Python import、调用点和现有 Contract 读取；本文只记录 V1 目标边界与当前实现的差距，不在 P1 修复。禁止依赖以[冻结规则](../architecture/dependency_rules.md)为准。下表的“耦合”不等于已发现 Safety 绕过。

## 已确认的边界差距

| 优先级 | 边界 | 当前证据 | 目标含义 |
| --- | --- | --- | --- |
| 高 | 通用 Core 含多旋翼/飞控/载荷语义 | [`contracts/core/effects.py`](../../contracts/core/effects.py#L11) 枚举 `ARM`、`TAKEOFF`、`BODY_VELOCITY_TARGET`、`SET_SERVO`，并引用 [`contracts.platform.field.ReferenceVersion`](../../contracts/core/effects.py#L8)；[`missions/core/production_catalog.py`](../../missions/core/production_catalog.py#L67) 使用 `uav.action.*` Schema 名 | V1 Core 不应预设 UAV、FIELD、servo；迁移时按 Vehicle/Application Capability 提供可用 Effect 与 Action |
| 高 | Action Registry 混合通用、车辆、比赛应用 | [`action_lab.py`](../../applications/cuadc_2026/actions/definitions.py#L102) 同时注册 takeoff、payload_release、GPS fusion、`select_drop_targets`；默认参数含 `bucket_*` 评分和比赛坐标，[具体片段](../../applications/cuadc_2026/actions/definitions.py#L129) | 在 composition root 合并 Core、Vehicle Plugin 与 Application Actions；逐项分类 |
| 高 | `telemetry_link` 混合三层 | [`LinkManager`](../../telemetry_link/link_manager.py#L328) 同时创建 `MavlinkClient`、状态缓存、队列及 writer；[`mavlink_client.py`](../../telemetry_link/mavlink_client.py#L15) 按 URL/baud 打开设备并持有 pymavlink；[`CommandSender`](../../telemetry_link/command_sender.py#L98) 编码具体飞控命令 | Vehicle Adapter / MAVLink Protocol / Transport 应独立；保留兼容 facade 直到消费者切换 |
| 高 | `SystemRunner` 汇集过多 owner | [`application/runner.py`](../../application/runner.py#L90) 直接组装 FieldService、ActionDispatcher、YOLO client、WebStatus、ServiceManager，循环中读取车辆与视觉、做融合并发布状态，[循环](../../application/runner.py#L222) | 逐步拆 composition、Runtime、World 发布及应用服务；同一时刻保留唯一生产调度和 writer |
| 高 | 独立诊断入口可直达 LinkManager 语义命令 | [`tools/telemetry_debug.py`](../../tools/telemetry_debug.py#L22) 创建 LinkManager，stdin 交给 [`dispatch_text_command`](../../telemetry_link/command_dispatcher.py#L65)，该函数直接调用 `arm` / `takeoff` / `set_servo` 等方法；不经过 ActionSafetyPipeline | 不是 `app/main.py` 的生产入口。默认 v2 broker context 为 send disabled，会拒绝常规命令；若启用 legacy writer，该工具的直接路径缺少 Action Safety 门禁。后续须纳入唯一出口审计，P1 不修改 |
| 中 | Mission 接口泄漏底层连接概念 | [`MissionOrchestrator.start/tick`](../../missions/engine.py#L127) 接受 `link_manager` 参数并向 Action Runtime 传递；当前生产调用传 `None`，[调用](../../application/mission_service.py#L327) | 没有发现 `missions/engine.py` 直接 import telemetry 或发送 MAVLink；但未来 Mission Contract 不应暴露连接参数 |
| 中 | Action 与 Guidance 依赖比赛 Field | [`goto_waypoint.py`](../../applications/cuadc_2026/actions/goto_waypoint.py#L7) 导入 `field.coordinates` / `FieldReference`；[`gps_target_lock.py`](../../applications/cuadc_2026/actions/gps_target_lock.py#L9) 导入 `gps_enu_deltas`；[`guidance/gps_derived_enu_fusion.py`](../../guidance/gps_derived_enu_fusion.py#L203) 在函数内导入 field 工具 | 通用 Action / Guidance 应依赖 Environment / Coordinate Contract；当前 Field 算法和安全前置条件不能提前删除 |
| 中 | Web 直接认识 Mission 具体模型与推进接口 | [`web_ui/routers/missions.py`](../../web_ui/routers/missions.py#L5) import `MissionActionStep` 并构造；[`web_ui/routers/actions.py`](../../web_ui/routers/actions.py#L37) 在 `/actions/start` 请求内调用 `mission.action_lab_tick()` | Web 应提交 Application 用例/DTO；启动后推进 owner 应明确。当前调用仍经 Action Runtime 与 Safety，不是硬件直发 |
| 中 | 感知接口依赖 UDP 与 YOLO 名称 | [`app/bootstrap.py`](../../app/bootstrap.py#L24) 创建 socket 并解析 YOLO UDP；[`yolo_app/main.py`](../../yolo_app/main.py#L79) 将 VideoSource、Tracker、UDP publisher、MJPEG 和录制组在一起 | 通过 CameraPort / PerceptionPort 发布数据；现有 UDP 在迁移期作 adapter |
| 中 | Core / Platform Contract 方向未统一 | [`contracts/core/common.py`](../../contracts/core/common.py#L9) 复用 `contracts.platform.common` 的 ID/Generation；[`contracts/core/effects.py`](../../contracts/core/effects.py#L8) 引用 Field version；`contracts/platform/ports.py` 仍命名为泛化 Vehicle Port | P2 应先核对既有类型归属，再建立必要 Contract；避免复制同义接口 |
| 低 | Field 语义进入 Web 状态层 | [`web_ui/status_adapter.py`](../../web_ui/status_adapter.py#L9) 导入 `RuntimeContextBuilder`；[`web_ui/context.py`](../../web_ui/context.py#L20) 生成 FIELD_REFERENCE audit | 作为当前 CUADC UI 合法存在，但不应成为通用 Web 的唯一 Environment 语义 |

## 对计划中几类疑似旁路的核查

| 检查项 | P1 结论 |
| --- | --- |
| `Core → hardware` | `contracts/core/` 未见直接 `pymavlink`、serial、RKNN 或 FastAPI import；但其 Effect/Field 类型有车辆和应用语义耦合。`application/runner.py` 是现有组合和运行 owner，不应把它误作纯 Core。 |
| `Mission → telemetry` | `missions/engine.py` 未直接 import telemetry；`link_manager` 参数是边界泄漏。 |
| `Action → MAVLink` | `missions/common/actions/*.py` 未见直接 `pymavlink` 或 `LinkManager` import；Action 通过 Result/Effect 间接发送。FIELD 与 UAV 参数仍耦合。 |
| `Web → hardware` | 路由经 `WebServices` / SystemControl / MissionControl；未发现路由直接 import `pymavlink`、serial 或 `LinkManager`。Web 仍直接 import Mission 模型和可触发 Action tick。 |
| `Perception → control` | `yolo_app/` 有目标锁定、录制等视觉控制接收与 UDP I/O；未发现直接 MAVLink 或 VehicleCommandPort 发送。视觉命令与车辆运动控制应保持区分。 |

静态扫描不能证明所有运行时路径安全；P1-03 从发送代码验证[安全基线](safety_baseline.md)。当前最值得先解决的结构问题是 **Contract 中的车辆语义归属**，并将独立诊断入口列入后续控制出口审计，而非先移动 `telemetry_link/` 或整批 Action 文件。P2 的第一个代码任务宜限定为 Contract inventory 与最小共用类型边界，并用 import 静态检查锁定方向；具体实施须待用户确认。
