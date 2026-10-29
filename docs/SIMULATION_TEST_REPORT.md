# 仿真系统测试与交付报告

> 2026-10-29 通用车辆组合阶段已继续更新。当前固定模型、多车、跨 World 和原生/Web 验收以 [通用仿真报告](UNIVERSAL_SIMULATION_TEST_REPORT.md) 为准；本页旧轮次数字保留为历史证据。
日期：2026-10-29（Asia/Ulaanbaatar）。基础实现提交 `b3e820a`；Rover 的退出停车确认问题随后按原安全边界定向修复，最终代码提交见机器索引。报告提交只整理文档与非敏感证据。原始大文件、进程日志、轨迹、EEPROM/签名临时状态和编译缓存不进入 Git。机器索引为 [center-evidence.json](simulation/center-evidence.json)，逐场景结论为 [兼容矩阵](GAZEBO_COMPATIBILITY_MATRIX.md)。

## 实际完成

60 个目录入口：24 个专项、28 个新增上游世界、8 个历史条目。39 项锁定资产记录世界、Fuel 模型和动态插件源码的来源、版本、SHA256、大小与许可证。Clearpath 六个世界、World Collection 迷宫/仓储/森林/城市/动态障碍、官方传感器/物理示例及部分 PX4 环境已实际加载。56 个入口通过本轮 L1/L2，4 个因已确认资源/部署缺口 BLOCKED；没有用下载 PASS 替代运行 PASS。

24 个专项世界全部通过 L1/L2。R05/C06 修复为配方 v2，并单独重测；其余配方 v1 的生成内容未改变。R01/Rover、C01/Iris Copter、F01/Twin Cessna Plane 通过 L1–L6，所有运动经原 Action/Execution/Authority/Safety/唯一 Writer。车辆验收固定为 seed=0、obstacle_count=0、无风、光照 0.8、摩擦 1；世界批测的 seed=42/默认障碍是另一配置，不把其 L1/L2 扩大为相同的 L4/L5。其余专项的车型和算法不据此扩展为通过。

| 等级 | 本轮 PASS / 目录入口 | 覆盖解释 |
|---|---:|---|
| L1 | 56 / 60 | 实际生成、SDF/资源与插件入口检查 |
| L2 | 56 / 60 | 原生 Gazebo 时间推进、错误扫描和自有进程清理 |
| L3 | 3 / 60 | 指定车辆配置的真实运动、初始/落地状态与独立真值 |
| L4 | 3 / 60 | 实际 Rover/Copter/Plane SITL 与基本运动 |
| L5 | 3 / 60 | 原 Framework 安全控制链和安全退出 |
| L6 | 3 / 60 | Chrome 选择场景/车辆、启动、真实 HTTP 控制/任务、报告与清理（指定无随机障碍的车辆配置） |

L3–L6 剩余 57 个入口未完成相应组合实测；VTOL 单独为 BLOCKED。上游模型/地图更多，并不代表更多经过验收的车辆组合。

## 三车型原生闭环

- Rover R01：模式、解锁/锁定、实际前进、转向、松开停止、Goto、原生返航、最终锁定；独立 Gazebo 轨迹核对停车。
- Copter C01：模式、解锁、1.5 m 起飞、平移/偏航、Goto、RTL 降落；检查真实高度、运动、地面状态及锁定。
- Plane F01：Twin Cessna 滑跑起飞、真实转弯、原生 Loiter、RTL 物理接近与 AUTOLAND，最终接地/锁定。飞行中检查速度大于 7 m/s，不以零速或多旋翼悬停模拟固定翼停止。

每次由真实 Chrome 登录统一会话，在 `/simulation` 选择场景与车型，调用真实后端启动；运动使用原 HTTP Action 控制接口。完成 Query Mission、报告 JSON 下载、截图和浏览器停止清理，JavaScript 无错误。Copter/Plane 的固定版本证据位于 `artifacts/simulation/center-20261029/frozen-regression/{copter,plane}/result.json`；Rover 停车修复后的两轮证据位于 `rover-hold-regression/run-{1,2}/result.json`。同目录包含 `web-control-truth.jsonl`、`browser-*.png` 与子会话 manifest。固定版本首次 Rover 失败原件 `frozen-regression/rover` 不被成功重测覆盖。先前开发侧三次 PASS 另保留于 `center-{rover,copter,plane}`，不能替代最终固定提交回归。

独立无车 Chrome 生命周期通过搜索、详情、启动、暂停、继续、重置、日志、导出、停止、共享登录导航；资产按钮实际完成锁定缓存的卸载/安装。证据分别位于 `artifacts/simulation-center/browser-world-r2/` 与 `browser-assets-r2/`。无车网页流程没有额外计入车辆 L6 数量。

## Mission、故障与安全合同

`mission-lifecycle/result.json`：真实新中心 Rover SITL 与 HTTP Mission API，Query 正常 SUCCEEDED、故意 false Condition 导致 FAILED、Wait 用户取消 CANCELLED、Sequence 超过任务总期限 TIMED_OUT；始终无 SEND/Lease，不冒充运动任务。

`mission-faults-rover/summary.json`：原有原生 Rover Mission 回归通过真实逻辑/事件/Timeout Recovery、手动与 Mission 冲突与交接取消、运动中失联 UNKNOWN、不释放不确定资源、重启无旧授权、旧输入拒绝和受控身份恢复。该结果是共享执行器回归，不扩大为其他地图或所有任务组合认证。

`software-faults-r5/result.json`：新 SoftwareFaultLink 实际接入自有 Rover TCP。观察到短暂字节块丢失并恢复；冻结签名遥测出现重放拒绝，原采样时间不更新。Manager 因状态过期 FAILED 后清理 COMPLETE，World L2 已通过的事实保留，两个 SEND 始终关闭，物理停止仍 UNCONFIRMED。全遥测中断/命令写前超时的范围是软件合同测试，没有声称飞控内部传感器融合故障。

865 项完整单元回归通过，0 failures/errors/skips，日志 `final-unit-r4.log`。新增合同覆盖跨浏览器 owner、CSRF/Origin/Host、任意命令/路径拒绝、默认 SEND、目录独占、取消就绪竞态、报告写入失败仍清理、版本 Fuel 文件围栏、缓存使用锁及不可用指标。完整单元不要求 ROS 常驻，也不把软件夹具结果计入原生等级。

Rover 的固定版本复跑曾在 Goto 退出失败，原因是 GUIDED 下转向衰减导致 StopMotion 确认偏晚，8 秒退出期限内未剩足 2 秒稳定窗。定向修复只在标准 Rover Goto 的原清零请求后加入已有原生 HOLD 制动，分别核验 StopMotion 与模式确认；UNKNOWN 任一项仍失败。速度/角速度阈值、原 8 秒期限、2 秒稳定窗、Lease 和 Writer 均未放宽。Copter 的退出没有加入 HOLD。两轮 Rover 完整网页闭环和原有 Rover 物理 Mission（Goto → ReturnHome → Disarm）重测通过。Goto 后的 Rover 保持 HOLD，后续 Goto/Drive 前需显式切换 GUIDED；该兼容变化已加入动作说明和使用指南。历史 RViz 的其他超时范围没有因此被宣称全部关闭。

## 资源、环境与性能

实际环境：Python 3.12.3、Gazebo Sim 8.15.0；可选隔离 ROS 2 Jazzy 已定位，未据此声称完成 ROS 多机部署。依赖在现有独立 `.venv` 中按 `python -m pip install -e '.[mavlink]' -r requirements-vision.txt` 安装。ArduPilot 三车型二进制使用已有隔离构建，未改外部 ArduPilot、Gazebo 插件、Twin Cessna 或 CUADC 项目。

World Collection 自定义动态对象插件按锁定原源码编译，链接 gz-sim8/transport13/msgs10，无缺失库；源码/二进制哈希与构建日志保留。R05/C06 另有 60 秒重力、接触、区域内动态目标探测，不将该子集当作车辆 L3。

仓库单独运行 60 秒基准、全部世界采样、固定种子重放与回归差异见 [性能报告](SIMULATION_PERFORMANCE_REPORT.md)。GPU 逐会话归因未知；不填入虚构数据。

普通 wheel 在全新独立环境安装所需 mavlink extra 后，从 `/tmp` 查询 60 个入口、生成内置世界和创建/取消会话通过；资产缓存使用用户可写位置。三车型以明确的外部 SITL/模型路径完成只读 preflight，实际输入文件均存在。wheel 含固定翼控制参数和静态资源，不打包大地图/日志/凭据。

## 失败原件与修复

首轮无车启动元数据错误保留 `world-batch/`；资源检测和软件故障的中间失败保留原目录，不覆盖。故障早期测试未观察到丢失时没有判为 PASS；确定性短暂丢失与签名冻结的成功重测为 r5。动态初探只证明运动，随后发现区域越界并补入更强边界 oracle，修复后 R05/C06 各 60 秒通过。UI 忙状态/登录修复前后的 Chrome 证据也保留。

历史八场景报告与未完成控制结论保持原样；本轮 H_warehouse 的锁定 Fuel 文件适配已通过重测。未通过/未执行的范围及四项资源阻塞见 [已知限制](SIMULATION_KNOWN_ISSUES.md)，不以其他模型、世界或历史 PASS 补填。

## 复现

```bash
# 默认无车辆运动：24 个世界、固定种子、逐项结果
./scripts/test_simulation_center.sh --run-dir artifacts/simulation/center-UNIQUE --physics --seed 42
# 显式授权只作用于本次自有 localhost SITL；仍经过原双 SEND 与 Safety
./scripts/test_simulation_center.sh --run-dir artifacts/simulation/center-full-UNIQUE \
  --kind rover --kind copter --kind plane --allow-send --faults --physics
# 任意一个已登记上游世界
vehicle-autonomy-simulation smoke --scene U_clearpath-warehouse \
  --seconds 60 --seed 42 --data-dir artifacts/simulation/warehouse-UNIQUE
# 真实反馈与故障/恢复回归
.venv/bin/python -m tests.simulation.phase4_faults --kind rover \
  --run-dir artifacts/simulation/mission-faults-UNIQUE
```

启动部署与一次登录流程见 [Web 使用指南](SIMULATION_WEB_UI_GUIDE.md)，资源/管理 API 见 [API 文档](SIMULATION_MANAGER_API.md)。所有数据目录使用新的名称；重启不接管旧 PID，不恢复 SEND。不连接实车，VTOL/未适配车型与未知扰动不会被界面放行。
