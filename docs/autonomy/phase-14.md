# P14 仿真对象输入验收

前置 P13 `ad9a5fa`。显式 `--sim-sensor-config` 加载白名单 target_1/2/3；配置声明 world→odom 刚体变换、来源、内容 SHA。只读 Gazebo Adapter 与 tests Oracle 各有独立 Node，不互相导入。Action/Mission 只见 immutable WorldObject，保持现有导航和 Vehicle Safety。

速度一的 Gazebo capture 映射独立 epoch；重复帧不刷新年龄，倒退/偏差使对象失效，队列只保留最新包。目标消失产 UNAVAILABLE tombstone，WorldModel 立即不再采用旧对象；Observation 同 producer 序号重复必须内容相同，冲突/逆序拒绝。App 状态记录 frame、来源、capture age、质量、Observation/校准版本；重连重建 producer/clock anchor。

测试 `python -m unittest tests.test_sim_objects -q` 3 项覆盖出现/移动/消失/过期、重复内容冲突、延迟/未来/跨域/倒退/偏差。实际 App `python -m tests.simulation.object_process` 在 owned SITL/Gazebo 观察三目标、通过测试专用 UserCommands 服务移动/删除 target_1，独立 Oracle 核验位置且默认 SEND 始终关闭。最新 `objects-*` PASS，所有自有进程/端口清理成功；首次 status 字段命名异常报告保留并修复。

P13 两车连续路线及失败场景已通过，完整最终回归证据待汇总补入。Gazebo fixture 的显式坐标关系仅属此仿真场景；不是真实感知或通用 world/odom 单位变换假设。服务仅用于测试刺激，传感器没有服务/发送 API。

Gazebo UserCommands 服务依据 [官方实体 API](https://gazebosim.org/api/sim/8/entity_creation.html)，loopback/隔离 partition 依据 [Transport 环境变量](https://gazebosim.org/api/transport/12/envvars.html)。
