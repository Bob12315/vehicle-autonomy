# V1 依赖规则

**状态：Frozen Target Architecture；后续源码修改必读。** 表中“允许”指通过 Contract 或明确 Port 依赖，不代表当前仓库已有对应目录或接口。具体迁移阶段见[当前状态](../migration/current_state.md)。

| 层 | 允许依赖 | 禁止依赖或直接调用 |
| --- | --- | --- |
| Core | 通用 contracts | 具体 Vehicle、MAVLink、USB、WebRTC、RK3588、CUADC |
| Mission | Action / World contracts、Mission validation | raw Vehicle Adapter、Protocol、Transport、驱动 |
| Action | Runtime、World、Planning / Guidance contracts | `pymavlink`、serial、socket、直接 `LinkManager` |
| Planning / Guidance | World / Planning contracts | Web、Transport implementation、绕过 Execution 的控制端口 |
| Intelligence | World / Mission / Intelligence contracts | `VehicleCommandPort`、Protocol、Transport、原始硬件 |
| Sensor Adapter | Sensor contracts、设备 I/O | Mission、决策、车辆控制 |
| Perception / Localization / Mapping | Sensor 与各自 contracts、World 发布接口 | Mission、Vehicle control、硬件命令 |
| World Model | 标准化 Observation、状态与 Environment contracts | 原始硬件 I/O、车辆命令 |
| Vehicle Plugin | Vehicle / Protocol contracts、Vehicle command port 实现 | Mission、Intelligence、Web |
| Protocol | Transport abstraction | Mission、AI、应用业务 |
| Transport | OS / device / network I/O | 业务 Core、GPS/ARM/takeoff 等语义 |
| Application / Web | Use Case / Application API | MAVLink、serial、硬件驱动、raw servo |
| Environment | 坐标、地图、区域与静态语义 contracts | Vehicle 控制与 Mission 决策 |
| Gateway | 物理设备访问、转发、链路健康与本地安全端口 | Mission、LLM 规划、高级自主决策 |

## 控制权限

```text
Mission / Intelligence / Web / Perception
                  │
                  ▼
          已注册 Action / Use Case
                  │
                  ▼
       Effect → Execution → Authorization → Safety
                                           │
                                           ▼
                                    VehicleCommandPort
```

上述层不能另建 writer、dispatcher 或发送通道。Safety 的拒绝、停止和失效处理必须作用于所有实际运动。具体定义见[Execution / Safety](../core/execution_safety.md)。车辆差异、协议语义和传输机制分别位于不同边界，详见[Vehicle Plugin](../platform/vehicle_plugin.md)与[Protocol / Transport](../platform/protocol_transport.md)。
