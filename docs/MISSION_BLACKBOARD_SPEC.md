# Mission Blackboard 规范

实现：`engine/mission/blackboard.py`、`studio_state.py`；基础时间与三态契约继续来自
`contracts/mission.py` 和已有 world query 模块。

## 声明与数据

变量声明包含 `schema`，可选 default、max_age_s、readonly、description、category、frame、
unit、origin。Schema 支持有界 JSON 类型、对象、集合和 anyOf；禁止远程 `$ref` 或可执行内容。
空间 category（pose、pose_stamped、geographic_coordinate、region、path）必须声明 frame、unit、
origin；时间基准来自原始 TimePoint 的 clock_domain_id 和单调时间，不能隐式换算。

```json
{
  "selected_targets": {"schema":{"type":"array","items":{"type":"string"}},"default":[]},
  "results": {"schema":{"type":"array","items":{"type":"integer"}},"default":[]}
}
```

每个值保留 value、observed_at、valid_for_ns、quality、frame、source，另有写入 revision 与
producer。复制、循环赋值、SubMission 返回、append 和并行提交不能把原观察时间刷新为当前时间。
聚合采用保守的最早时间和最短有效期。缺失、过期、未来时间、不同时间域、无效质量或错误坐标系
都不能用于放行控制；Condition 得到 UNKNOWN，Action 输入不能提交为正常值。

单值最多 16 KiB。图像、点云、视频应声明 artifact_reference 类型的元数据对象，传递 URI、
散列、类型等引用；本模块不会自动下载或把媒体字节塞进 Blackboard。

## 作用域和引用

| 引用 | 语义 |
|---|---|
| mission.name | 根 Mission 变量；在 SubMission 内指该子任务自己的局部 Mission 变量 |
| submission.name | 最近子任务的显式输入 / 输出端口 |
| loop.index / current_item / iteration_id | 当前顺序迭代快照，索引与迭代身份独立 |
| node.node_id.output.field | 当前上下文中已声明、已产生的上游结果 |
| local.name | 当前有声明的局部变量；不隐式创建变量 |

对象字段和集合索引必须通过声明的类型路径访问。子任务不能越过自身边界拾取同名父节点输出；
需要的父数据必须显式映射输入。每个 Action 执行另有独立 Node scope，保存契约默认值解析后的
实际参数、绑定来源、覆盖来源和已声明结果。未声明输出 Schema 的结果只作诊断，不冒充类型化变量。

ForEach 启动时只读取一次集合，最多 20 次，每轮创建独立 loop scope；不会重新给目标盖新时间戳。
子任务调用拥有独立 submission scope，输入、局部变量、输出不能重名。

## 并行与外部输入

并行分支将外部变量写入暂存区。发布时拒绝同一变量的并发写入；运行时再检查 revision 和重复
写入，整体通过后提交。Any 成功取消的分支不会把部分结果提交到父 Blackboard。

World 是只读查询，当前开放的标量路径以 `/api/studio-b/catalog` 为准。导航目标引用由应用层
只读适配器提供原始提案时间，且校验车辆、epoch、odom 和到期时间；不会创建 Action 或控制权。
模板保存移除具体 Tool 提案绑定，并要求明确补齐输入后才能发布。

Inspector 展示 scope、类型、值、producer、原始时间、有效性、消费者和变更历史。历史滑块按事件
重建只读值与节点状态，不回写执行器。应用重启后的记录是历史快照，不能拿来恢复旧控制授权。
