# Mission Studio B 使用指南

## 启动和登录

在现有隔离环境与已安装的本机仿真环境中：

```bash
cd /home/level6/vehicle-autonomy-framework
.venv/bin/python -m vehicle_autonomy.app.visualization.launch \
  --kind copter --allow-send --gazebo-gui --studio-demo
```

打开 `http://127.0.0.1:8781/studio`。首次登录使用启动目录下
`simulation/web-token.private` 中的 Web 密钥。密钥只在登录时提交，之后复用统一 HttpOnly 会话；
刷新或切换 Dashboard、Vehicle Control、Tool Manager 不重复输入。退出或会话失效后重新登录。
不要把密钥写进网址。Agent 使用独立凭据。

启动器提供自有 SITL、Gazebo、Web 和已连接的 Desktop Agent。RViz/QGC 等仍在 Tool Manager
显式启动。`--studio-demo` 只注册软件示例和模板，不会自动运行、解锁或起飞。
省略 `--allow-send` 时部署 SEND 关闭。每个真实控制 Run 仍要明确勾选自己的 SEND。

Rover 改为 `--kind rover`，页面端口 8780；Plane 改为 `--kind plane`，页面端口 8782。
建议逐个启动测试，使用 Ctrl+C 关闭本次启动器。指定 `--run-dir` 时必须使用新目录；
保留旧目录用于审计，不删除旧 Mission 数据。固定翼模板仅用于当前已审计的跑道、50 m 起飞和
634 m AMSL 目标配置，不是通用机场任务。

## 创建、编辑和发布

1. 进入 Mission Library，新建任务、复制现有任务，或在 Templates 中“从模板创建”。
2. 选择目标车辆，设置名称和新版本号。
3. 从左侧后端 Registry 生成的节点库拖入 Action；拖动输出端口到输入端口。
   Action → Action 用 next；ForEach 用 body；Condition 用 true/false/unknown。
4. 拖动空白平移、滚轮缩放；Shift 多选/框选，支持复制、粘贴、删除、Undo/Redo、布局和分组。
   已知循环、重复入口即时拒绝；最终权威检查在后端。
5. Basic 中编辑 Schema 生成的参数；选择固定值、Blackboard、上游输出或只读 World。
   Goto 的 x/y/z 可选择已有 RViz odom 提案，只导入数据，不执行运动。
6. Advanced 配置输出变量，可以从输出 Schema 创建变量或结果列表；复杂声明、失败策略和
   空间元数据可在 Mission 设置和高级 JSON 中维护。空间变量需要明确坐标系、单位和原点。
7. 自动保存状态显示修订号。冲突时本地修改保留，可以加载服务器草稿、导出本地版本或另存。
   离线时保持当前编辑器，恢复网络后重试；未保存时关闭页面会提示。
8. 点击“验证”，修复类型、端口、能力、资源和依赖错误，再“发布版本”。发布后不可覆盖；
   编辑后使用新语义版本。运行不会直接使用未发布草稿。

Parallel 可添加分支端口，设置 all/any、并发上限及 join_id，并把分支接到显式 Join。
Join 前的结果应显式写入不同 Blackboard 变量；禁止两个分支并发修改同一个变量。

## 子任务

从已发布 SubMission 库插入节点，在 Basic 选择固定版本并映射输入，Advanced 映射输出。
双击进入子画布，通过面包屑返回。发布版本只读；“编辑为新版本草稿”不会升级原父图的依赖。
父图必须明确选择新版本并重新发布。

选中单入口单出口的线性 Action/Wait 后，可以“组合为 SubMission”。父图和子任务草稿一次保存。
先在 Library 发布子任务，再发布父任务。复杂选区会给出拒绝原因；可以单独创建完整子图再插入。

## 执行和调试

Runner 中选择发布版本。原生控制任务勾选 SEND，核对确认框中的实际目标后运行；软件示例可保持
SEND 关闭。若 Vehicle Control 已占用目标，先在那里释放。连接状态不代表获得控制权。

请求发送、后端接受、Action 执行、Action 完成和实际确认是不同阶段。Diagnostics 包含原始命令
结果、MAVLink ACK 与 Driver 状态证据。固定翼 GUIDED/LOITER/RTL 的节点成功表示契约所定义的
配置采用，不表示已到达或已经降落。

在编辑器给节点设置执行前断点后发布；Debug Run 会在可确认的安全点暂停。
安全暂停不冻结 Action Runtime 或飞控控制器，期限也不会延长。连续运动或保留飞行控制权时
可能一直显示 PAUSE_REQUESTED，需要取消或明确请求安全退出，不能把它看作已经暂停。
固定翼含控制 Effect 的图不支持逐节点运动单步；只读图仍可调试。

- Resume：重新检查新鲜遥测、原车辆 session/origin、资源和状态后继续。
- Retry：仅安全失败且契约允许的节点，次数有界。
- Skip：仅待执行/安全失败且明确允许跳过的节点。
- 参数覆盖：仅已发布契约允许的待执行参数；审计单独记录，不修改版本。
- Cancel：请求原 Action 的车型安全退出；UNKNOWN / UNCONFIRMED 继续阻止新控制。
- 人工接管：确认后停止新调度并请求退出。仅 SUSPENDED 且安全释放后，进入 Vehicle Control
  点击 SEND ON。任务不会自动恢复；手动控制结束要先释放，再明确 Resume。
  如果接管中断了一个活动 Action，V1 保留记录但不自动重建该 Action；需明确创建新验证的运行。
  固定翼空中保留的原生控制权可能不能确认释放，此时接管保持阻塞，不强行解除安全边界。

重启后旧 Run 仅供观察，不恢复旧授权或控制器。History 滑块只回放事件、节点和 Blackboard；
读取旧记录不表示其中的目标仍是当前有效数据。

## 示例

`CUADC_MultiTarget_Simulation` 是纯软件场景：三个筒的尺寸来自声明的场景几何，像素框面积特意
不同，选择 T-02、T-03。两个 ForEach/HandleTarget scope 分别追加结果。把 DetectContainers 的
simulate_target_loss 设为 true，可验证一次目标丢失的 Recovery 和独立库存结果。
所有操作均声明 `simulation=true`、`physical_action_confirmed=false`；不进行真实起飞、投放或降落。

真实链路使用另三个模板：Rover_Inspection、Copter_Inspection、Plane_Inspection。
不要把软件示例的通过等同于真实飞行或载荷成功。它们的实际结果和限制见测试报告。

## 复现测试

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m tests.simulation.studio_b_browser --demo \
  --output artifacts/mission-studio-b/my-browser-test
.venv/bin/python -m tests.simulation.studio_b_native --kind rover --browser \
  --run-dir artifacts/mission-studio-b/my-rover-test
```

原生脚本只创建并连接明确自有的新仿真进程；路径必须是新目录。Copter 同样支持 `--browser`。
本机固定翼二进制在项目已有构建中，因此本轮使用：

```bash
VAF_SIMULATION_SITL_BIN_DIR=/home/level6/vehicle-autonomy-framework/artifacts/phase2-control/ardupilot-source/build/sitl/bin \
  .venv/bin/python -m tests.simulation.studio_b_native --kind plane --browser \
  --run-dir artifacts/mission-studio-b/my-plane-test
```

当前安装环境是测试前提；环境变化时应先运行已有仿真预检，不连接真实硬件来替代 SITL。
