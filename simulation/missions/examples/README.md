# Mission 示例（Studio schema 2）

六份 JSON 可以导入当前 Mission Studio；对应模板会在已连接明确自有的仿真车辆后，
进入“任务编排 → 模板”时出现。无需 `--studio-demo`。创建模板不会发布或运行任务。

| 文件 | 任务 | 车型 | SEND |
| --- | --- | --- | --- |
| `01_state_survey.json` | 顺序采样三次状态，每次间隔约 0.5 秒，示范 ForEach 和结果追加 | 三车型 | 关闭 |
| `02_disarmed_branch.json` | 新鲜上锁状态走成功；已解锁走失败；缺失/过期走 UNKNOWN | 三车型 | 关闭 |
| `03_ground_patrol.json` | 直线前往 (1,0)、(2,0)、(3,0) 米，每站停留，在第三站停车上锁 | Rover | 显式开启 |
| `04_air_hover_land.json` | 起飞至 1.5 米，等待 2 秒，再原地降落并观察上锁 | Copter | 显式开启 |
| `05_air_survey_return.json` | 1.5 米高度依次前往 (1,0)、(1,1)，返航降落 | Copter | 显式开启 |
| `06_runway_inspection.json` | 50 米起飞、配置目标、盘旋、RTL、AutoLand | Plane | 显式开启 |

## 在控制台使用

1. 使用 `./control-center` 启动，登录后在仿真中心创建并启动对应车辆，等待新鲜遥测。
2. 进入“任务编排 → 模板”，选择任务，“从模板创建”。也可以导入本目录 JSON。
3. 在编辑器明确选择验证实例。文件中的 rover/copter/plane 是示例目标；模板复制和导入会清空旧绑定，
   控制台分配的实际 target 通常带 simulation 前缀。
4. 验证并发布版本，再进入运行页，明确选择实际执行实例并核对 vehicle_id、System ID、World/Session。
   前两份保持 SEND 关闭；运动任务确认目标和 SEND。发布版本不会被运行绑定改写。
5. 运行后查看节点结果、Blackboard、命令证据和最终状态。取消请求不代表物理停止已确认。

模板按车型安装，已存在的模板、草稿和发布版本不覆盖。复制模板会清空旧目标；
换 World 或重连后执行选择失效，必须重新选择实例。不会自动恢复旧任务或授权。

## 参数与结果

- 地面车和多旋翼 Goto 的坐标是当前受测仿真装配的 `odom` 坐标，单位米，
  不是相对车辆当前位置的位移。本例以部署原点附近空旷区域为前提。
- 地面车 Goto 安全退出会进入 HOLD，后续每段先显式 SetMode GUIDED；
  本例使用有限 Goto，不把持续 Drive 的超时冒充成功或停车。此例结束于第三站，
  不自动返航，也不宣称已具备任意折线、障碍物或动态避障能力。
- 多旋翼 Wait 是流程等待，保持行为由原 GUIDED/飞控链负责；它不是新增悬停控制器。
  Land / ReturnHome 的成功必须包含原合同要求的落地和上锁观测。
- 固定翼复用已有受测跑道任务，目标高度固定为 634 米 AMSL。
  SetGuidedTarget / Loiter / RTL 节点成功只确认配置采用，实际着陆由 AutoLand 验证。
  不适用于任意机场、出生高度或其他未验收机型。
- 三次采样的完整观测在各次 GetVehicleState 结果中。Blackboard 只汇总小体积的车型和
  read_only 标志，不复制整套遥测到一个可能超出预算的大数组。
- 上锁分支只演示三态条件，不能据此推定 GPS、定位、校准或整车运动资格。

全部示例只用于已审计的自有本机 SITL，不增加实机控制授权。沿用原 Action、Execution、
双 SEND、SafetyPolicy、Lease、TTL、会话围栏和唯一 MAVLink writer。

## 开发验证

```bash
.venv/bin/python -m unittest tests.mission_studio.test_mission_examples -v
.venv/bin/python -m tests.simulation.mission_examples --kind rover --allow-send \
  --run-dir artifacts/mission-examples/my-rover-run
```

Copter / Plane 分别替换 kind。每次使用全新目录；仅启动自有 loopback 仿真实例，
通过 HTTP 保存、验证、发布和运行，用独立 Gazebo truth 核对运动与最终停止/落地。
