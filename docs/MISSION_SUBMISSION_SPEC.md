# SubMission 规范

子任务与主任务使用相同的 schema 2 Definition，并声明 `interface.inputs` / `interface.outputs`。
端口声明与 Blackboard 变量声明相同。依赖必须是已发布的 `mission_id@version`；没有浮动 latest。

```json
{
  "node_id":"handle", "type":"SubMission",
  "sub_mission":{"mission_id":"HandleTarget","version":"1.0.0"},
  "input_bindings":{"target":{"ref":"loop.current_item"}},
  "output_bindings":{"task_result":{"ref":"mission.results","mode":"append"}}
}
```

编译时检查输入覆盖、类型、输出目标、依赖存在性和递归（最多 8 层）。所有子图资源并入父任务的
原资源组，由同一 Action Runtime、Control Authority 和安全边界管理。子任务不会建立第二条命令链。

调用时为 inputs、outputs 和局部 Blackboard 创建新的 scope，保留传入数据的原时间、质量和坐标系。
成功返回前要求声明的输出确实存在且有效；不会用缺省正常结果伪造成功。各端口的原始元数据保留在
执行记录中，聚合结果使用保守有效期。子任务总期限不超过其自身期限和调用节点期限。

每次 ForEach 调用有独立 scope、execution_id 和输入输出记录。一个目标失败后进入 Recovery 时，
不会覆盖另一轮结果。不可确认的物理退出仍阻止 Recovery 或后续控制。

## 编辑和版本

- 从已发布 Library 插入节点，选择明确版本，映射 Basic 输入和 Advanced 输出。
- 双击进入子画布，面包屑返回。发布内容只读；“编辑为新版本草稿”保留旧版本。
- 新版本发布后，父节点仍固定原版本。必须明确选择新引用并重新验证、发布父任务。
- Graph Diff 能比较图结构、参数和版本内容；恢复为新草稿不会修改历史 Run。
- V1 支持将单入口、单出口的 1..16 个线性 Action/Wait 原子提取为子任务草稿。
  提取保留外部输入、输出和后续节点的数据引用；先发布子任务，再发布父任务。
  多出口、复杂复合图、多次写同一外部变量或选区内修改后又读取外部变量的提取会拒绝。
  这些复杂子任务仍可独立创建完整图并从 Library 插入，不会静默丢弃数据语义。

## HandleTarget 示例

通过 `--studio-demo` 显式注册纯软件场景后，初始化 HandleTarget 1.0.0 和 CUADC 模板。
输入 target、simulated_payload_slot、remaining_in；输出 operation_status、task_result、current_target、
remaining_out。内部 Recovery 的 try 分支确认目标并记录软件操作，recover 分支记录模拟丢失。

该示例不调用旧 CUADC 工程，不产生 Vehicle/Payload Effect，不进行真实瞄准、释放计算或执行器
触发；ReturnAndLand 也是明确的软件结果。真实车辆链路由独立的 Rover/Copter/Plane 巡检模板验证。
