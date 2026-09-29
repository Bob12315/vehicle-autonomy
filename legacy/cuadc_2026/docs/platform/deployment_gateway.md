# Deployment 与 Vehicle Gateway

**状态：Frozen Target Architecture。** onboard、server、hybrid 是三种部署概念；当前项目主要有 RK3588 onboard 实现，server / hybrid 仅定义边界，尚未实现为通用方案。

| 模式 | 组件位置 | 关键约束 |
| --- | --- | --- |
| onboard | Sensors、Perception、Mission、Planning、Safety、Vehicle Link 主要在机载电脑 | 本地设备与控制闭环可用 |
| server | 主要计算在服务器，车端保留 Vehicle Gateway | 服务器不能直接假设访问 `/dev/video*`、`/dev/ttyUSB*`、CAN 或本地传感器 |
| hybrid | 机载保留 basic perception、local safety、local planning、emergency functions、gateway；服务器可运行 LLM、VLM、heavy perception、global planning、semantic reasoning | 断链时车端必须按明确策略安全退化 |

Deployment Profile 只决定组件在哪运行以及如何连接，不改变 Action、Mission、Execution / Safety 的业务语义。系统配置由 Deployment、Vehicle、Environment、Mission Profile 组合，可再选 Sensor、Perception、Transport、Intelligence Profile；组合不是固定飞机配置。

Vehicle Gateway 是 server / hybrid 的基础设施，负责 physical device access、sensor/video/telemetry forwarding、command receiving、link health、local watchdog 和 emergency fallback。它不承担 Mission、LLM planning 或高级自主决策，也不能建立绕开 Authorization / Safety 的日常命令入口。Gateway 需保证命令时效、断链停止和本地安全执行边界，具体协议和实现后续设计。

```text
onboard: Sensors → Onboard Computer → Vehicle Link
server:  Server Components ⇄ Vehicle Gateway ⇄ Local Devices / Vehicle
hybrid: Server Intelligence ⇄ Vehicle Gateway ⇄ Onboard Safety / Vehicle
```

示例组合：`onboard + multirotor + serial/MAVLink + USB camera + RK3588 YOLO + cuadc_2026 + rescue_2026`；另一组合可以是 `server + rover + network/MAVLink + WebRTC camera + campus + patrol`。后者是目标示例，**不是当前已支持配置**。

目标 Profile 组合示意，不是当前配置文件的 Schema：

```yaml
deployment: {mode: onboard}
vehicle: {type: multirotor, profile: ardupilot_quad}
transport: {type: serial, protocol: mavlink}
sensors: {camera: usb_nadir, lidar: none}
perception: {profile: rk3588_yolo}
environment: {profile: cuadc_2026}
mission: {profile: rescue_2026}
intelligence: {enabled: false}
```

```yaml
deployment: {mode: server}
vehicle: {type: rover}
vehicle_link: {transport: network, protocol: mavlink}
sensors: {camera: {source: webrtc}}
environment: {profile: campus}
mission: {profile: patrol}
```
