# Vehicle Autonomy Framework V1 项目重构执行计划

目标仓库：

`Bob12315/vehicle-autonomy-framework`

本计划用于把当前以 CUADC 2026 多旋翼、RK3588、ArduPilot、YOLO/RKNN 为中心的项目，逐步迁移为真正可扩展的：

# Vehicle Autonomy Framework

本计划已经作为 V1 架构重构基线。

后续所有重构均必须遵守本计划以及新的 Architecture Freeze 文档。

---

# 0. 总目标

最终框架必须能够在不修改 Stable Core 的情况下组合：

```text
Deployment
×
Vehicle
×
Transport
×
Protocol
×
Sensors
×
Perception
×
Environment
×
Mission
×
Intelligence
```

目标支持：

```text
Multirotor
Rover
Fixed Wing
VTOL
future vehicles
```

以及未来：

```text
Camera
LiDAR
Radar
Depth Camera

YOLO
SLAM
VIO
Depth Estimation

LLM
VLM
Policy Model
Agent

Onboard
Server
Hybrid
```

当前 CUADC 2026 系统最终只能成为：

```text
一个 Multirotor + ArduPilot + RK3588 + CUADC Environment + Rescue Mission 的具体实例
```

而不是 Framework 本身。

---

# 1. 冻结总体架构

控制链：

```text
Operator / External System
          ↓
      Application
          ↓
   Intelligence（可选）
          ↓
       Mission
          ↓
        Action
          ↓
 Planning / Guidance
          ↓
        Effect
          ↓
      Execution
          ↓
    Authorization
          ↓
        Safety
          ↓
   Vehicle Plugin
          ↓
      Protocol
          ↓
      Transport
          ↓
  Physical Vehicle
```

状态链：

```text
Physical Sensors
        ↓
Sensor Adapters
        ↓
Perception
Localization
Mapping
        ↓
    World Model
        ↓
 ┌──────┼────────┐
 ↓      ↓        ↓
Mission Planning Intelligence
```

Environment：

```text
Environment
     ↓
World Model
```

Deployment：

```text
Deployment
```

只决定组件运行在哪里：

```text
Onboard
Server
Hybrid
```

不改变业务语义。

---

# 2. 永久架构不变量

下面规则从 P0 开始永久生效。

## Core 不知道具体车辆

禁止：

```python
if vehicle_type == "rover":
    ...
elif vehicle_type == "multirotor":
    ...
```

出现在通用 Core。

车辆差异必须进入：

```text
vehicles/<vehicle_type>/
```

---

## Action 是预定义能力

Action 必须：

```text
提前实现
提前定义 Schema
提前测试
提前定义输入输出
提前定义 Safety 边界
```

AI、Mission、Web 都只能使用已经注册的 Action。

不得动态创造新的底层控制能力。

---

## Mission 只组合 Action

Mission 不知道：

```text
MAVLink
CAN
PWM
Serial
UDP
USB
Flight Controller
```

Mission 只负责任务流程。

---

## 所有运动只有一个出口

永久保持：

```text
Action
→ Effect
→ Execution
→ Authorization
→ Safety
→ VehicleCommandPort
```

禁止任何旁路：

```text
Mission → MAVLink
Planner → pymavlink
LLM → VehicleCommand
VLM → VehicleCommand
YOLO → Flight Controller
Web → Servo
```

---

## SEND 默认关闭

当前：

```yaml
executor:
  send_commands: false
```

必须一直保持默认关闭。

代码迁移不得降低当前安全门禁。

---

## 不建立第二套控制链

迁移期间：

```text
旧链
+
新链
```

不能同时成为生产 writer。

允许：

```text
new adapter
new contract
compatibility wrapper
shadow/read-only implementation
```

但同一时刻只能有：

```text
一个 production command writer
```

---

# 3. 重构方法

禁止 Big-Bang Rewrite。

必须采用：

```text
Contract
↓
Compatibility Adapter
↓
Move Ownership
↓
Switch Consumer
↓
Tests
↓
Delete Legacy
```

而不是：

```text
先删旧代码
↓
再重写整个系统
```

每次只迁移一个清晰的架构边界。

---

# 4. 阶段总览

```text
P0  Architecture Documentation Freeze

P1  Repository Baseline & Dependency Map

P2  Common Contracts & Core Boundary

P3  Vehicle Plugin Architecture

P4  Protocol / Transport Separation

P5  Sensors / Perception / World Model

P6  Environment / Mission Decoupling

P7  Deployment / Gateway Architecture

P8  CUADC Application Migration

P9  Second Vehicle Proof

P10 Legacy Cleanup & V1 Architecture Audit

P11 Intelligence Layer
    （暂不实施，只保留接口）
```

严格按依赖顺序执行。

---

# P0 — Architecture Documentation Freeze

## 目标

完成之前已经确定的文档重置。

当前仓库仍是旧：

```text
CUADC
RK3588
ArduPilot
YOLO/RKNN
UAV
```

文档体系。

先删除旧 docs，建立新的 Vehicle Autonomy Framework 文档。

至少完成：

```text
README.md
AGENTS.md

docs/
├── README.md
├── architecture/
├── core/
├── platform/
├── intelligence/
├── migration/
└── examples/
```

新增：

```text
docs/migration/refactor_plan_v1.md
```

将本计划完整写入该文件。

## 验收

确认：

```text
README 不再把 CUADC 当项目主体
AGENTS 使用新 Architecture Rules
CUADC 被定义为 Example
Target 与 Current Implementation 明确区分
```

本阶段禁止修改业务代码。

---

# P1 — Repository Baseline & Dependency Map

这一阶段仍然不做大规模移动。

## P1-01 当前源码清点

扫描整个仓库。

建立：

```text
docs/migration/current_code_map.md
```

至少映射：

```text
app/
application/
missions/
guidance/
execution/
telemetry_link/
fusion/
field/
yolo_app/
web_ui/
config/
tests/
```

到目标架构。

例如：

```text
telemetry_link
→ Vehicle + MAVLink Protocol + Transport 的混合实现

yolo_app
→ Camera Adapter + Perception + Media Streaming 的混合实现

field
→ Environment 的旧实现

missions/common/actions
→ Common Action + Multirotor Action 混合
```

不要仅看文件名。

必须读取源码判断真实职责。

---

## P1-02 Dependency Audit

生成：

```text
docs/migration/dependency_audit.md
```

识别：

```text
Core → hardware
Mission → telemetry
Action → MAVLink
Web → hardware
Perception → control
```

等违反未来边界的依赖。

先记录。

不要立刻全部修改。

---

## P1-03 Safety Baseline

确认当前真实控制路径。

必须从源码验证，不依赖旧文档。

记录：

```text
Action
→ Runtime
→ Dispatcher
→ Safety
→ command writer
→ MAVLink
```

当前真正的：

```text
SEND gate
authorization
deadman
cancel
stop
ACK
writer ownership
```

必须记录。

创建：

```text
docs/migration/safety_baseline.md
```

这将成为整个迁移期间的安全回归基线。

---

# P2 — Common Contracts & Core Boundary

## 目标

先建立稳定 Contract，不立即移动所有实现。

目标：

```text
contracts/
├── core/
├── vehicle/
├── sensor/
├── perception/
├── world/
├── planning/
├── environment/
└── intelligence/
```

只建立当前迁移真正需要的类型。

不要建立几十个空接口。

---

## P2-01 Core Types

整理：

```text
RunId
ActionId
MissionId
Timestamp
Result
Health
Capability
```

已有成熟类型优先迁移或复用。

禁止为了“新架构漂亮”重新发明已有稳定类型。

---

## P2-02 Effect

继续保留 Typed Effect 思路。

Effect 必须成为：

```text
Action
和
Side Effect Execution
```

之间唯一正式协议。

Effect 本身不包含：

```text
pymavlink object
socket
file handle
hardware instance
```

---

## P2-03 Runtime Input

定义统一：

```text
RuntimeInputSnapshot
```

其数据未来主要来源：

```text
WorldSnapshot
VehicleState
SystemState
RunState
```

禁止 Action 在执行周期中到处直接读取 live hardware getter。

---

## P2-04 Static Dependency Tests

增加自动测试：

Core 禁止 import：

```text
pymavlink
serial
socket implementation
RKNN
FastAPI
vehicles.multirotor
vehicles.rover
```

这些测试后续永久保留。

---

# P3 — Vehicle Plugin Architecture

这是第一次真正的大边界迁移。

目标：

```text
vehicles/
├── multirotor/
├── rover/
├── fixed_wing/
└── vtol/
```

本阶段只完整迁移：

```text
multirotor
```

其他车辆暂时不要实现真实控制。

---

## P3-01 Vehicle Contracts

冻结：

```text
VehicleStatePort
VehicleCommandPort
VehicleCapabilities
VehicleHealth
VehiclePlugin
```

不要让 Port 暴露 MAVLink message。

---

## P3-02 Multirotor Plugin

建立：

```text
vehicles/multirotor/
├── plugin.py
├── capabilities.py
├── state/
├── commands/
├── actions/
└── safety/
```

当前 UAV 特有语义逐步迁入这里。

---

## P3-03 Action 分类

扫描当前 Action。

分成：

```text
Common Action
Vehicle-specific Action
Application-specific Action
```

例如可能：

Common：

```text
wait
record
observe
condition
```

Multirotor：

```text
takeoff
land
body_velocity
condition_yaw
```

CUADC Application：

```text
select_drop_targets
gps_fuse_views
payload-specific logic
```

不要简单把所有 `missions/common/actions` 整个移动到 Multirotor。

先按语义分类。

---

## P3-04 Action Registry

Action 注册必须由组合阶段完成。

例如：

```text
Core Actions
+
VehiclePlugin.actions
+
Application Actions
```

生成最终：

```text
ActionRegistry
```

Core 不知道具体 vehicle type。

---

## P3-05 Capability Validation

增加：

```text
VehicleCapabilities
```

Mission 启动前能够发现：

```text
unsupported action
unsupported capability
```

例如 Rover Mission 调用 takeoff：

必须在执行前失败。

---

# P4 — Protocol / Transport Separation

当前 `telemetry_link` 不直接整包移动。

先拆职责。

## P4-01 Transport

建立：

```text
infrastructure/transports/
```

首批仅抽象已有实际使用方式：

```text
serial
udp
tcp
```

Transport 负责：

```text
open
close
send bytes
receive bytes
connection lifecycle
```

Transport 不知道 MAVLink 语义。

---

## P4-02 MAVLink Protocol

建立：

```text
protocols/mavlink/
```

负责：

```text
MAVLink encode/decode
message handling
ACK semantics
MAVLink command construction
```

不负责：

```text
Mission
Action
Environment
AI
```

---

## P4-03 Vehicle Adapter

最终形成：

```text
VehicleCommand
      ↓
Multirotor Vehicle Adapter
      ↓
MAVLink Protocol
      ↓
Transport
```

状态反向：

```text
Transport
↓
MAVLink Protocol
↓
Multirotor State Mapper
↓
VehicleState
```

---

## P4-04 Compatibility Migration

现有 `telemetry_link` 先允许成为 compatibility facade。

不要第一天删除。

执行顺序：

```text
introduce contracts
→ wrap old telemetry
→ switch one consumer
→ verify
→ switch remaining consumers
→ delete old facade last
```

---

# P5 — Sensors / Perception / World Model

## P5-01 Sensor Contracts

建立：

```text
CameraFrame
PointCloudFrame
SensorHealth
CameraPort
```

当前只真正实现 Camera。

LiDAR 只定义未来扩展边界。

不要现在写 LiDAR driver。

---

## P5-02 Camera Migration

当前摄像头来源统一成：

```text
CameraPort
→ CameraFrame
```

实现至少保留：

```text
USB
```

未来预留：

```text
WebRTC
RTSP
Simulation
```

但本阶段不实现完整 WebRTC。

---

## P5-03 yolo_app 拆分

当前 `yolo_app` 很可能同时承担：

```text
camera input
preprocess
inference
tracking
UDP
Web stream
recording
```

不要一次性重写。

先明确拆分边界：

```text
Camera Adapter
↓
Perception Pipeline
↓
PerceptionResult
```

旧 UDP 可以暂时作为 adapter。

---

## P5-04 PerceptionPort

上层不再依赖：

```text
YOLO UDP packet
```

而依赖：

```text
PerceptionPort
```

具体来源可以是：

```text
YOLO RKNN
future VLM
simulation
remote inference
```

---

## P5-05 World Model V1

建立最小：

```text
WorldSnapshot
```

第一版只整合当前真正已有的信息：

```text
vehicle state
pose
velocity
health
perception targets
environment reference
timestamp
```

不要一次设计全能世界模型。

---

## P5-06 WorldSnapshot Consumer Migration

逐步让：

```text
Mission
Action
Planning
```

读取 WorldSnapshot。

不要直接读取：

```text
YOLO receiver
raw telemetry
camera
```

---

# P6 — Environment / Mission Decoupling

## P6-01 Environment Contract

建立：

```text
EnvironmentProfile
EnvironmentSnapshot
CoordinateReference
NamedLocation
Zone
Geofence
```

只实现当前真正需要部分。

---

## P6-02 Field Migration

当前 Competition Field 逻辑迁移到：

```text
environments/cuadc_2026/
```

旧：

```text
Field Reference
Competition Field
drop area
recon area
```

不再属于 Framework Core。

---

## P6-03 Generic Environment

至少支持：

```text
none
generic_gps
generic_local
cuadc_2026
```

UI 可以选择 Environment Profile。

---

## P6-04 Mission 去场地硬编码

当前 Mission 中类似：

```text
x = 0
y = 32.5
```

逐步改为：

```text
environment location reference
```

例如：

```text
$environment.locations.drop_center
```

不要一次修改所有 Mission。

先选择一个 Mission 完整迁移并验证。

---

# P7 — Deployment / Gateway Architecture

## P7-01 Deployment Profile

支持概念：

```text
onboard
server
hybrid
```

当前完整支持：

```text
onboard
```

---

## P7-02 Vehicle Gateway Contract

建立：

```text
gateway/
```

Gateway 负责：

```text
physical device access
telemetry forwarding
sensor forwarding
command reception
link health
watchdog
```

不负责 Mission。

---

## P7-03 Server Transport Boundary

定义：

```text
RemoteVehicleLink
RemoteCameraSource
```

只定义边界和测试 fake。

不要立刻实现完整生产 WebRTC/公网控制。

---

## P7-04 Onboard Compatibility

当前 RK3588 部署改成：

```text
Deployment Profile = onboard_rk3588
```

而不是 Framework 默认平台。

---

# P8 — CUADC Application Migration

创建明确的应用层：

```text
applications/
└── cuadc_2026/
```

这里拥有：

```text
CUADC Mission
drop logic
recon logic
payload scoring
CUADC environment
CUADC-specific configuration
```

框架 Core 中不再出现：

```text
bucket
drop zone
recon area
rescue_2026
CUADC
```

---

## P8-01 Example Mapping

最终能够明确表示：

```text
Deployment:
onboard_rk3588

Vehicle:
multirotor

Protocol:
mavlink

Transport:
udp/ethernet or serial

Sensors:
usb camera

Perception:
yolo_rknn

Environment:
cuadc_2026

Application:
cuadc_2026

Mission:
rescue_2026
```

---

## P8-02 Regression

原比赛系统迁移完成后必须保持已有功能。

至少验证：

```text
Mission loading
Action registry
Web UI
telemetry
perception
Field/Environment
SITL
Safety gates
SEND false
```

---

# P9 — Second Vehicle Proof

这是证明架构真的解耦的重要阶段。

不要马上做完整 Rover 自动驾驶。

建立最小：

```text
vehicles/rover/
```

只实现：

```text
capabilities
state schema
fake adapter
basic action registry
safety schema
```

可以使用：

```text
FakeRover
```

测试。

例如支持：

```text
stop
drive_velocity
goto_ground
```

不接真实车。

---

## 架构验收标准

加入 Rover 后：

```text
Core 不需要修改
Mission Runtime 不需要修改
World Model Core 不需要修改
Protocol abstraction 不需要修改
```

如果为了增加 Rover 必须大量修改 Core：

说明 Vehicle Plugin 边界设计失败。

返回 P3 调整。

---

# P10 — Legacy Cleanup

只能在：

```text
新 owner 已运行
消费者已切换
测试通过
兼容路径没有调用方
```

后删除旧代码。

删除顺序：

```text
legacy wrappers
old adapters
old directories
deprecated config
deprecated imports
deprecated docs references
```

不能因为目录名字“不漂亮”提前删除。

---

# P11 — Intelligence

本阶段现在不实施。

只保留：

```text
contracts/intelligence/
intelligence/
```

未来用于：

```text
LLM
VLM
Laya
Agent
Mission Planner
```

永久边界：

```text
Intelligence
→ Intent / MissionProposal / SemanticObservation / PolicyDecision
```

禁止：

```text
Intelligence → VehicleCommandPort
```

未来单独制定：

```text
Intelligence Architecture V1
```

本次重构不要顺手实现。

---

# 5. 最终目标目录

代码迁移完成后目标大致为：

```text
vehicle-autonomy-framework/
│
├── app/
│
├── application/
│
├── core/
│   ├── runtime/
│   ├── mission/
│   ├── action/
│   ├── execution/
│   ├── safety/
│   └── lifecycle/
│
├── contracts/
│   ├── core/
│   ├── vehicle/
│   ├── sensor/
│   ├── perception/
│   ├── world/
│   ├── planning/
│   ├── environment/
│   └── intelligence/
│
├── vehicles/
│   ├── multirotor/
│   ├── rover/
│   ├── fixed_wing/
│   └── vtol/
│
├── sensors/
│   ├── camera/
│   ├── lidar/
│   ├── radar/
│   ├── gps/
│   └── imu/
│
├── perception/
├── localization/
├── mapping/
├── world_model/
│
├── planning/
├── guidance/
│
├── intelligence/
│
├── environments/
│
├── applications/
│   └── cuadc_2026/
│
├── missions/
│
├── protocols/
│   └── mavlink/
│
├── infrastructure/
│   └── transports/
│       ├── serial/
│       ├── udp/
│       └── tcp/
│
├── gateway/
├── deployment/
├── web_ui/
├── config/
├── runtime/
└── tests/
```

这是目标。

不要通过一次巨大 commit 强行达到。

---

# 6. 配置体系目标

逐步从当前：

```text
app.yaml
telemetry.yaml
yolo.yaml
competition field
```

迁移为组合 Profile：

```text
config/
├── runtime/
├── deployments/
├── vehicles/
├── transports/
├── sensors/
├── perception/
├── environments/
├── applications/
└── missions/
```

一个最终 Runtime Profile 类似：

```yaml
deployment:
  profile: onboard_rk3588

vehicle:
  type: multirotor
  profile: ardupilot_quad

vehicle_link:
  protocol: mavlink
  transport: ethernet_udp

sensors:
  camera:
    profile: usb_nadir

perception:
  profile: yolo_rknn

environment:
  profile: cuadc_2026

application:
  profile: cuadc_2026

mission:
  profile: rescue_2026

intelligence:
  enabled: false
```

Profile resolver 应在 composition root 完成。

Core 不直接读取 YAML。

---

# 7. Composition Root

最终所有具体实现只允许在：

```text
app/bootstrap
composition root
```

组装。

例如：

```text
load DeploymentProfile
load VehiclePlugin
load Transport
load Protocol
load Sensor adapters
load Perception provider
load Environment
load Application plugin
build Core runtime
```

禁止业务模块自己：

```python
if config.vehicle == "multirotor":
    from vehicles.multirotor ...
```

这些选择必须集中在 composition root。

---

# 8. 测试策略

每阶段必须优先增加测试，而不是最后统一补。

需要长期保留以下类别：

```text
architecture dependency tests
contract tests
vehicle plugin tests
mission validation tests
action tests
safety tests
transport tests
protocol tests
world model tests
environment tests
Web/API tests
SITL regression
```

---

# 9. 安全测试门禁

任何涉及：

```text
Execution
Safety
VehicleCommand
Protocol writer
Transport writer
continuous control
servo/payload
```

的修改必须额外验证：

```text
SEND=false
unauthorized command rejected
stale command rejected
stop/cancel works
link loss fails safe
continuous command deadman works
old generation cannot replay
```

---

# 10. 测试顺序

每一个阶段：

```text
static checks
↓
unit tests
↓
contract tests
↓
integration fake
↓
existing regression
↓
SITL
```

禁止直接以真机作为代码迁移验证。

---

# 11. 真机规则

除非用户在当前会话明确授权：

禁止：

```text
arm
takeoff
land
servo
payload
motor
vehicle movement
real SEND
```

连接真机做只读检查也必须说明。

重构默认：

```text
offline
fake
SEND=false
SITL
```

---

# 12. Git 工作方式

开始任务前：

```bash
git status
git branch --show-current
git log -1 --oneline
```

如果工作树有用户未提交修改：

不要覆盖。

记录并避开。

---

每个重构单元应该尽量保持：

```text
一个架构问题
一个明确 commit
一组对应测试
```

不要生成：

```text
"refactor everything"
```

这种数万行不可审计 commit。

---

# 13. Codex 每次工作的格式

每次只执行一个：

```text
P?-??
```

开始前报告：

```text
Task
Current owner
Target owner
Dependencies
Files expected to change
Safety impact
Tests
Rollback path
```

然后执行。

完成后报告：

```text
Changed
Not changed
Tests
Architecture impact
Compatibility
Remaining legacy
Next task
```

不要自动开始下一任务。

---

# 14. 删除代码规则

任何 Legacy 删除必须满足：

```text
1. 新实现真实存在
2. production consumer 已切过去
3. tests 覆盖
4. repo search 无有效调用者
5. rollback 不再依赖旧代码
```

五项满足后才删除。

---

# 15. 当前优先级

目前不要做：

```text
LLM
VLM
Laya
LiDAR
WebRTC production
Rover real hardware
Fixed Wing
VTOL
```

当前目标不是增加新功能。

当前目标是：

> 让现有 CUADC 多旋翼系统首先成为新 Framework 上运行的第一个 Application。

做到这一点后，再扩展能力。

---

# 16. 第一阶段执行指令

现在开始执行。

首先：

```text
P0 — Architecture Documentation Freeze
```

完整执行 P0。

完成 P0 后：

只执行：

```text
P1-01 — Current Source Code Map
P1-02 — Dependency Audit
P1-03 — Safety Baseline
```

P1 只做分析和文档，不移动业务代码。

P1 完成后停止，并向用户提交：

```text
1. 当前源码 → 新架构映射
2. 最大耦合点
3. Safety 当前真实控制链
4. 哪些模块可以直接保留
5. 哪些模块必须拆分
6. 推荐第一个代码迁移任务
```

在用户确认之前：

不要开始 P2。

---

# 17. 完成定义

V1 Framework 重构完成必须满足：

```text
Core 不知道 CUADC
Core 不知道 RK3588
Core 不知道 ArduPilot
Core 不知道 MAVLink
Core 不知道具体 Vehicle
```

同时：

```text
CUADC 2026 可以作为 Application 正常运行
Multirotor 通过 Vehicle Plugin 接入
MAVLink 是 Protocol
USB/UDP/TCP 是 Transport
Camera 是 Sensor
YOLO 是 Perception
Field 已成为 Environment
RK3588 已成为 Deployment Profile
```

并且添加一个 Fake Rover 时：

```text
无需修改 Core
```

这才表示 Vehicle Autonomy Framework V1 架构迁移真正完成。

---

现在严格从 P0 开始。

先检查工作树和当前源码事实。

不要开始大规模代码移动。