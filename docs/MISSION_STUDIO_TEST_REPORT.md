# Mission Studio B 验收报告

日期：2026-10-29。仓库：Vehicle Autonomy Framework。

## 交付内容

完成“Library → Graph 编辑 → 参数/Blackboard 绑定 → 验证 → 草稿保存 → 不可变发布 →
执行 → Runner/Debug → History”的实际链路。新入口 `/studio`；原 schema 1 编辑器保留在
`/studio/legacy`。没有创建第二个执行器，没有修改旧 CUADC 项目，也没有删除历史 Mission 数据。

关键模块：

| 模块 | 已实现职责 |
|---|---|
| engine/mission/studio_graph.py、graph.py | schema 2、类型/车型/依赖/资源验证、兼容迁移、派生树防篡改 |
| graph_runtime.py、studio_state.py | 原 scheduler 扩展、ForEach、SubMission、并行、调试和独立执行记录 |
| blackboard.py | 强类型作用域、原始时间/质量、只读来源、并发暂存及原子合并 |
| app/mission_designer/studio_* | CAS 草稿、发布/模板、Diff、导入导出、选区封装及应用用例 |
| app/web/static/studio-* | 共用画布、动态 Action 库、递归参数表单、运行检查和只读回放 |
| actions/simulation/studio_demo.py | 明确标识、零 Effect 的软件场景与目标丢失恢复 |
| visualization/goals.py | 既有 RViz 提案的只读数据适配，不创建 Action 或控制权限 |

前端沿用现有 vanilla JS、console CSS 和统一登录。长期 Web 密钥只在登录时提交；Cookie、CSRF、
Origin 和后台权限检查继续共用。没有为新页面开放匿名控制，也没有把 Agent 凭据交给浏览器。

## 自动化结果

| 阶段 | 结果 |
|---|---|
| 修改前完整单测 | 773 项通过 |
| 编译器及运行能力首轮 | 794 项通过 |
| Library/Editor/Runner 集成 | 799 项通过 |
| 示例、作用域及数据导入 | 810 项通过 |
| 最终完整回归 | **813 项通过，111.017 秒** |
| Studio 专项组合测试 | **40 项通过** |
| 实际 Chrome 软件环境测试 | **通过，pageerror 0** |
| 完整启动器 + SITL/Gazebo + Desktop Agent | **通过；Agent 已连接；自动执行 Action/Mission 均为 0；默认部署 SEND 关闭** |

最终命令：`python -m unittest discover -s tests -v`。完整套件覆盖原 Action、Mission、Control
Authority、Safety、车辆控制、Tool Manager/Agent、Workspace 和认证等既有模块；没有用跳过安全
检查来通过测试。日志位于本机 `/tmp/vaf-studio-final-813.log`。

Chrome 测试通过真实用户操作检查：Library 首屏、HTML 拖拽、端口连线、对象/数组/布尔参数、
输出变量创建、复制粘贴删除、Undo/Redo、CAS 自动保存、验证发布、断点/单步/恢复、子图展开、
Runner 更新、两次 CUADC 子任务结果、登录刷新与跨页保持、平板布局。它使用隔离软件 Driver，
不作为物理飞行证据。

软件示例正确选择物理尺寸最小的 T-02、T-03；像素框面积不能替代尺寸。另测目标丢失 Recovery、
两轮数据隔离、库存结果和 `physical_action_confirmed=false`。这些结果不是实际投放。

## 原生 SITL / Gazebo / Chrome

下列三次均由 Chrome 从 Template 创建、发布并明确授权 Run，经过原 HTTP、Mission、Action、
安全与 Vehicle/Protocol/Transport 链路。Gazebo 独立真值另行采样。

| 车型 | 实际操作 | 最终独立测量 | 结果 |
|---|---|---|---|
| Rover | GUIDED、Arm、1 m 巡检、Stop、返回、Stop、Disarm | 返回误差 0.36988 m；速度 0.000256 m/s | 通过 |
| Copter | GUIDED、Arm、1.5 m 起飞、移动观测、ReturnHome 并降落 | 返回误差 0.00610 m；速度 0 m/s；地面高度差约 0 m | 通过 |
| Plane | MANUAL、Arm、50 m 原生起飞、GUIDED 配置、观测等待、LOITER、RTL、AUTOLAND | 返回误差 1.25752 m；地面高度差 0.000035 m；速度 0.56970 m/s | 通过既有跑道降落阈值 |

固定翼最终速度阈值沿用既有 `<1 m/s` 契约，不声称完全静止；GUIDED/LOITER/RTL 的配置 ACK
没有被当成位置到达。没有给 Plane 使用多旋翼悬停或零电机暂停指令。三个浏览器均无 pageerror。

证据目录：

- `artifacts/mission-studio-b/native-rover-final-browser/`
- `artifacts/mission-studio-b/native-copter-final-browser/`
- `artifacts/mission-studio-b/native-plane-final-browser/`
- `artifacts/mission-studio-b/browser-final/`
- `artifacts/mission-studio-b/full-launch-smoke/`

目录中的 studio-summary.json、manifest.json、轨迹、命令结果和截图可复查。原生场景结束时，
各自 Gazebo/SITL 进程退出码均为 0，remaining_process_groups 为空。启动器冒烟测试正常退出。
运行目录因含私有状态被 Git 忽略；脱敏汇总已保存为
[evidence/mission-studio-b.json](evidence/mission-studio-b.json)，界面截图为
[evidence/mission-studio-b-editor.png](evidence/mission-studio-b-editor.png)。

收尾按 manifest 的 PID 与 start_ticks 检查：没有仍运行的本轮自有测试进程；
8780、8781、8782、18881 均未监听。保留证据，未留下自动运行任务。

原生测试在开发过程中的源快照执行：Rover 的 Git HEAD 为 e5d04ca（带正在开发的代码），Copter/
Plane 为 a5e2a2d；各 manifest 另外保存实际源文件 SHA256。934f5c3 是之后的并行合并修复，由
嵌套 Blackboard、SubMission-in-Parallel、Any 异步取消组合测试和最终 813 项回归验证。
不把不同源快照的多轮测试描述成同一次冻结全产品原生验收。

## 发现并修复的问题

- 未声明 output_schema 的历史 Action 被错误当成 null 输出：保留诊断结果，禁止冒充类型化输出。
- 节点选择重建 DOM 导致双击失效：选择保持 DOM，只有实际拖动才写布局。
- 新 Run 请求期间仍显示旧成功状态：单独显示发送/接受阶段并阻止重复点击。
- 参数对象多字段编辑及数组增加项丢更新：维护当前表单值并重建数组项。
- 并行 Any 异步退出后漏合并、后台节点误标成功：退出确认后仅合并成功分支，取消节点保持取消。
- 原子合并前未完整检查目标/帧/事件预算，以及嵌套分支提前写父级：加入预检和逐层暂存合并。
- 子任务同名输出可能拾取父级值：查找不得跨越子任务边界。
- 默认 Plane 二进制路径缺失：使用本机已有项目构建路径重跑，真实通过；没有以 Mock 替代。

## 控制和安全结论

既有双 SEND、明确 SafetyPolicy、Lease/TTL、session/generation fence、独立 Action Runtime 和唯一
MAVLink writer 均继续使用。Mission 不能隐式抢占 Vehicle Control；未知退出不能作为安全释放。
暂停不冻结控制器，接管需要明确触发；只有确认安全释放才进入 SUSPENDED。Resume 检查新鲜状态、
原 session/origin 和资源，且不会自动重建被中断的 Action。运行定义始终固定。

## 限制与未验证内容

- 未连接、未控制、未验收真实硬件；未进行真实感知识别、瞄准或载荷操作。
- QGC 目标导入和未审定的 map 坐标变换未实现；当前支持 RViz odom 位置数据。
- 选区提取仅支持闭合线性 Action/Wait；复杂子图可独立创建、发布和引用。
- 跨检查点重建/回滚属于 Level 3，未实现；活动 Action 被接管中断后不能假装原地恢复。
- 固定翼控制图不提供运动单步；空中保留的原生控制权可能阻止确认接管，不强制释放。
- 调试/故障组合主要以软件运行器验证；三车型原生测试验证正常任务链，不声称覆盖全部耐久和
  原生故障注入场景。没有重跑项目所有多小时物理验收总集。
- 复杂空间声明/失败策略仍使用高级 JSON；资源、图深度、历史及持久化均有明确预算。

## Git 与操作说明

开发提交：c13a5e0（审计契约）、e884cbe（编译/运行）、e5d04ca（Library/UI）、a5e2a2d
（示例/调试/输入）、934f5c3（并行安全修复）。文档与脱敏证据另作收尾提交；没有强制推送。

启动、编辑、发布、运行、调试和复现命令见 [使用指南](MISSION_STUDIO_USER_GUIDE.md)。
Schema、Blackboard、SubMission 规范以及架构文档均已补齐。
