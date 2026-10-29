# Mission Studio B Schema（schema_version 2）

实现入口：`engine/mission/studio_graph.py`、`graph.py`。编辑器、HTTP API 和未来 AI
均提交同一份 JSON Definition。`schema_version: 1` 的原执行器入口继续保留；不会改写旧文件。

## 定义、草稿、版本与运行

- Definition：`mission_id`, `schema_version`, `revision`, `version`, `name`, `target`,
  `supported_vehicles`, `nodes`, `edges`, `blackboard`, `interface`, `execution_policy`,
  `resource_requirements`, `failure_policy`, `sub_mission_references`, `metadata`。
- Draft：Definition 加保存状态、更新时间和散列。保存必须携带 `expected_revision`。
  成功后 revision 加一；冲突返回 HTTP 409 和 `conflict.current`，不覆盖另一编辑器。
- Version：`mission_id@version` 的不可变发布记录，包含规范化定义、散列、编译快照和依赖。
  修改内容或布局后再次发布，应使用新的语义版本。
- Run：已有 Mission Journal 中的一次执行，固定该版本及依赖快照，保存车辆、Provider、
  资源组和命令证据。编辑草稿不改变 Run。
- Node Execution：独立 `execution_id`、源 Mission/节点、运行节点 ID、scope、输入、输出、
  时间和状态。ForEach 的每一轮以及 Retry 的每一次尝试分别记录。
- Event：Run 内递增 sequence、稳定事件 ID、原始单调时间和结构化字段。

`mission_id` 使用原 Mission 的有界标识规则；版本为 `major.minor.patch`。
`node_id` / `edge_id` 为 `[A-Za-z][A-Za-z0-9_-]{0,63}`，在各自定义内唯一。

## 最小可执行图

```json
{
  "schema_version": 2,
  "mission_id": "wait_demo", "revision": 0, "version": "1.0.0",
  "name": "等待示例", "target": "copter", "supported_vehicles": ["copter"],
  "nodes": [
    {"node_id": "start", "type": "Start"},
    {"node_id": "wait", "type": "Wait", "parameters": {"duration_s": 1}},
    {"node_id": "end", "type": "End"}
  ],
  "edges": [
    {"edge_id": "e1", "source": "start", "target": "wait", "port": "next"},
    {"edge_id": "e2", "source": "wait", "target": "end", "port": "next"}
  ],
  "blackboard": {}, "execution_policy": {"timeout_s": 60}, "metadata": {}
}
```

`target` 必须对应当前装配的 Driver。保存未连完的草稿是允许的，发布必须通过权威验证。

## 节点与端口

| type | 端口 / 配置 |
|---|---|
| Start / End | Start 必须有 next；End 用 outcome 表达 SUCCEEDED / FAILED / UNKNOWN |
| Action | `action_type`, 固定 `action_contract_version`, parameters, input_bindings, output_bindings；next / failure |
| Condition | true / false / 可选 unknown / next；execution_policy.expression |
| ForEach | body / next；collection 引用、max_iterations 1..20、on_item_failure abort / continue |
| Parallel | branch:0..15 / next；completion all / any，max_concurrency；可指定 join_id |
| Join | 共享控制流只允许进入显式 Join；next |
| Wait | parameters.duration_s；或 policy.mode=condition + expression；或 mode=event + event 名称 |
| SubMission | 固定 mission_id + version；参数及输入输出端口映射；next / failure |
| Sequence / Recovery / Retry | child:N；try / recover；body + count 1..3；均可接 next |

Condition 仅允许 eq/ne/lt/le/gt/ge/all/any/not 的受限表达式，保留三态语义。
没有 Python、JavaScript 或 Shell 表达式入口。Unknown 分支仍受原执行器的只读安全约束。

节点 policy 可设置 timeout_s。Action 可请求 skippable、runtime_overrides，但必须同时得到
ActionSpec 契约许可。failure_policy 支持 abort / branch / retry；不确定副作用不会自动重试。

## 绑定

```json
{
  "input_bindings": {"count": {"ref": "mission.value", "max_age_s": 3}},
  "output_bindings": {"count": {"ref": "mission.results", "mode": "append"}}
}
```

引用见 [Blackboard 规范](MISSION_BLACKBOARD_SPEC.md)。固定值与绑定不能同时提供同一参数。
Action 输出必须声明 Schema 才能用于类型化数据流；未声明结果只提供诊断检查。
输出字段 `result` 保留为“整个 Action 结果”；其他键支持结果字段路径。

外部只读目标示例：

```json
{"source":"external","provider":"navigation_goal","id":"goal-id",
 "path":"position.x","frame":"odom","max_age_s":30}
```

该引用不包含凭据，也不授予 SEND。当前只安装了 RViz 目标提案的位置数据适配器；
要求目标车辆和 epoch 匹配，最长 30 秒，不进行 map 变换或方向控制。QGC 导入未安装。

## 编译、验证与边界

编译器将图转换为已有 scheduler 使用的派生树，并嵌入 `studio.definition`、散列和依赖快照。
外部提交派生树时重新编译并比较，不能修改派生节点绕过源图验证。没有第二套执行器。
验证覆盖端口、可达性、循环、类型、资源、并行写入、Action 版本、车型和 SubMission 递归。
应用层还检查外部 Provider 绑定；运行准入继续执行原动态状态、安全和权限检查。

预算：源图 128 节点 / 256 边 / 128 KiB；编译图 512 节点、深度 64、Action 预算 256；
Mission 总期限最多 1800 秒。嵌套结构同时受预算限制，并非任意组合都可达到各项上限。

显式迁移保留常见线性 Action/Wait、观察绑定、输出映射和 Condition；不支持的历史结构
会拒绝转换并保留原件，可继续使用 `/studio/legacy` 和 schema 1 执行入口。
