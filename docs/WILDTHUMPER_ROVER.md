# 普通 Rover 更换为官方 WildThumper

日期：2026-11-08。普通 Rover 的固定车辆库和 `start_rover_sim.sh` 入口使用
ArduPilot 官方 Wild Thumper 6WD。Web 车辆类别 ID 仍为 `rover`，页面显示
“WildThumper 六轮车”。本次不连接实机，不改变原运动授权、安全策略和唯一 Writer。

## 来源与安装

- 上游：[ArduPilot/SITL_Models](https://github.com/ArduPilot/SITL_Models)
- 固定提交：`25bc38ed8c6c0345840159a8cbc0b02781d52f3c`
- 模型：`Gazebo/models/wildthumper/model.sdf`，包含六轮、摩擦、惯性、IMU 和 ArduPilotPlugin。
- [官方使用说明](https://github.com/ArduPilot/SITL_Models/blob/25bc38ed8c6c0345840159a8cbc0b02781d52f3c/Gazebo/docs/WildThumper.md)
  使用 `rover-skid` 参数；保留本程序已有遥测、低速航点和 RTL 参数。
- 官方说明将外观模型归功于 GrabCAD 的 Pamir；本仓库不分发第三方网格、纹理或上游源码，
  也不将官方托管等同于第三方外观资源的再分发许可。

在检出外准备一份固定版本，例如：

```bash
git clone --filter=blob:none --no-checkout https://github.com/ArduPilot/SITL_Models.git /absolute/external/SITL_Models
git -C /absolute/external/SITL_Models sparse-checkout set Gazebo/models/wildthumper Gazebo/docs
git -C /absolute/external/SITL_Models checkout --detach 25bc38ed8c6c0345840159a8cbc0b02781d52f3c
```

在原有 `environments/tools.local.toml` 的 `[paths]` 中增加
`sitl_models_root = "/absolute/external/SITL_Models"`，保留已有其他配置。
也支持 `VAF_SITL_MODELS_ROOT`。普通启动不会下载资源或修改外部源码。
车辆库核对全部模型、网格、纹理及执行依赖的 SHA256；缺失或变化时阻止启动，
不会退回旧模型。模型版本、来源与锁见 `simulation/vehicles/catalog.json`。

## 装配、坐标与兼容范围

每个车辆实例仍使用独占模型副本、独立端口和系统 ID。仅在副本中修改身份、
本地 FDM 端点与显示话题，并按原机制装配前视相机和可选 MID-360。
上游质量、惯性、碰撞、六轮关节、摩擦和执行器 PID 保持原值。

出生高度为当地平面上 0.15 m，与官方示例一致。新车 `base_link` 与模型原点重合，
不沿用旧车 0.19 m 的车体偏移；MID-360 位于 base 上方 0.22 m。
安装支架仅为示意外观，不增加质量或碰撞。RViz 的明确标注示意车辆显示六轮。
相机仍为前视相机。安全围栏保持 ±5 m，速度、TTL、Lease、双 SEND 和停止确认不变。

在控制台选择普通 Rover、创建新仿真即可使用新车；已有模型实例不在运行中热替换。
旧 `target_rover` / `compact_rover` 仅保留为显式历史模型/导航测试夹具，旧前轴导航资格
不自动转授给 WildThumper。本次不新增 Nav2、路径规划或 SLAM 控制闭环。

此前 MID-360 目标二的旧 Rover 误差、回环和重复运行证据属于旧模型，不能作为
WildThumper 的完整 SLAM 验收；目标二仍需按新模型独立完成后续验收。

## 本轮验收

所有证据位于 `artifacts/wildthumper-20261108/`，仅使用本机 Gazebo / ArduPilot SITL。

| 检查 | 结果 | 证据 |
|---|---|---|
| 浏览器选择、新模型启动、原 HTTP 控制链 | PASS | `control-r1/result.json` |
| 解锁/上锁、HOLD、直行、原地转向、Goto、RTL 与安全退出 | PASS | `control-r1/web-control-result.json` |
| 六轮模型、相机及 MID-360 原生联合回归 | PASS，25 项 | `mid360-r1/result.json` |
| 全量单元回归（包含保留的目标二工作区修改） | PASS，1081 项，137.014 s | `unittest-final.log` |
| 仅本次待提交代码的独立快照 | PASS，53 项定向测试；wheel 构建及内容审计通过 | `index-targeted.log`、`wheel/audit.json` |
| 新车型逐切片 FAST-LIO 静态接入、地图保存加载 | PASS，仅静态接入，非运动精度验收 | `timed-lio-smoke/lio-result.json` |
| 单脚本入口模型解析、固定源检查及独占装配 | PASS | `standalone-preflight.json` |
| 最终 Gazebo 外观、前视相机及零运动写入 | PASS，已查看截图 | `final-visual-r4/visual-result.json` |
| 最终所属进程与外部源检查 | PASS，所属进程无残留，上游源码未修改 | `final-audit.json` |

基础控制中实际直行 0.505 m、转向 0.404 rad；停止后平移速度分别为
0.00481 m/s 和 0.000918 m/s；返航距出生点 0.123 m。所有运动均由原 Action 链执行，
不是 Gazebo 位置设置或另一个 MAVLink 控制器。

命令：

```bash
.venv/bin/python -m tests.simulation.center_vehicle --kind rover --run-dir artifacts/wildthumper-20261108/control-r1 --allow-send
.venv/bin/python -m tests.simulation.mid360 --run-dir artifacts/wildthumper-20261108/mid360-r1 --allow-send --gui
.venv/bin/python -m unittest discover -s tests -v
```

逐切片静态接入生成并重新加载了 9577 点地图；这不替代目标二的三轮运动精度、
回环、重定位和控制台完整验收。25 项原生回归另已验证 Copter 运动、原 RS16、
相机、未启用 MID-360、多实例、录制回放、索引恢复及所属进程/端口清理。

主要修改文件：车辆库及来源锁、HostEnvironment 外部模型索引、原单脚本入口、
MID-360 装配与六轮示意模型、车辆选择名称、新出生高度场景、相关测试及本文档。
冻结合同、Core、Action/Vehicle 运动执行没有修改。

最终实景截图：`final-visual-r4/gazebo-wildthumper.png`；前视图：
`final-visual-r4/front-camera.jpg`。补拍脚本的早期入口/环境与启动观察失败记录
保留在 `final-visual*.log`，最终采用与原生 GUI 验收一致的图形库环境并等待实际就绪。

正式提交与最终证据索引在提交后写入 `artifacts/wildthumper-20261108/delivery.json`。
本次不自动合并或推送。
