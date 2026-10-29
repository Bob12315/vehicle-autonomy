# 仿真中心已知限制与阻塞

日期：2026-10-29（Asia/Ulaanbaatar）。本轮限定自有 localhost Gazebo / SITL，不连接真实飞控或车辆。实际结果与证据位置见 [测试报告](SIMULATION_TEST_REPORT.md) 和 [兼容矩阵](GAZEBO_COMPATIBILITY_MATRIX.md)。

## 尚未完成的目标

- 24 个专项配置均可生成独立世界，但只有 R01/Rover、C01/Iris Copter、F01/Twin Cessna Plane 接入了受控车辆启动组合。其余 21 个专项世界的车辆运动、专属感知与导航任务尚未验收，前端禁用相应车型选择。
- F07 提供 VTOL 测试环境几何；本机已审计模型中没有合格 QuadPlane 模型与专属控制 profile。悬停/过渡为 BLOCKED，不能把普通 Plane 模式接口当作 VTOL 支持。F08 没有完成空地协同和多机通信隔离实测。
- 传感器取自现有车辆模型；本页不更改安装位置、噪声、外参，也不注入飞控内部 GPS/IMU/气压计故障。无 GPS 导航、目标识别、视觉降落、搜索和避障算法没有因地图存在而完成。
- 可配置障碍数量、随机种子、风向/风速、光照和地面摩擦；任意出生点、任意障碍坐标、传感器组合及任务难度表单尚未开放。场景的固定出生点/目标区来自受信配置。
- 风字段与 WindEffects 是真实世界配置，但其是否影响 ArduPilot JSON 耦合机型的动力学尚未做有/无风对照。河流表面为几何/视觉标识，没有水动力模型。多楼层/丘陵是工程测试几何，没有完成车辆可通行性认证。
- 软件故障影响 Framework 接收链路；延迟、丢包和冻结有本轮真实 SITL 证据。全遥测中断和写前命令超时有软件合同测试，未单独完成真实运动故障验收。丢包单位为 TCP 接收字节块，不是 IP 数据包；不改变飞控自身 EKF 融合。
- 暂停/继续/重置仅对无车世界开放。活动 SITL 的严格时钟、身份与权限围栏不允许原地重置；需要结束并创建新 epoch。
- 图像是明确标注的静态场景示意。没有在浏览器伪装 Gazebo 实时 3D 或摄像头流；原生 RViz2 接口保留。无头加载不等于人工逐项检查纹理、视觉效果和所有碰撞网格。
- Manager 会话仅自动记录可证实的 L1/L2；完整 L3–L6 结论由本轮独立原生/浏览器验收程序及汇总矩阵给出，不依据连接、ACK 或页面加载自动升级等级。JSON 导出保留其原始保守等级。
- 尚无长时间耐久、全部车型/地图交叉组合或性能容量认证。8 秒世界冒烟与单个仓库基准的覆盖范围在性能报告中分别列明。

## 资源阻塞

| 入口 | 已确认原因 | 复现 / 后续工作 |
|---|---|---|
| U_ardupilot-gimbal | 缺少固定版本的 Oak tree、Pine Tree、ground_station、Walking person、Prius Hybrid 等 Fuel 资源 | 查询资产状态；补齐许可证、版本、哈希和递归依赖后重新检查，不能自动抓取 latest 冒充锁定资源 |
| U_px4-forest | grasspatch 与树木等 Fuel 引用未完整锁定/安装 | 使用已有可用的 Clearpath Orchard 或 World Collection Forest；本入口继续 BLOCKED |
| U_px4-moving-platform | 缺少专属 moving_platform 模型和控制插件 | 已从固定提交核对原模型确实引用 `libMovingPlatformController.so`；模型文件存在不等于此自定义插件已按 Harmonic 构建/验收 |
| H_multiagent | 历史条目仅为 ROS launch 参考，没有独立可生成 SDF，也没有经本轮验证的 ROS 多机部署 | 不作为第八个可运行世界；建立独立部署与通信隔离测试后再开放 |

精确缺失引用保存在 `artifacts/simulation/center-20261029/blocked-details.json`。PX4 模型来源为[固定版本模型文件](https://raw.githubusercontent.com/PX4/PX4-gazebo-models/e5997f455e33ec071c7c677fc59a65781de496a4/models/moving_platform/model.sdf)。GitHub API 检查遇到速率限制后已改用同一官方仓库固定提交的原始文件核对，未使用不可信镜像。

旧 H_warehouse 的固定版本 Fuel `/files/...` 网格引用已适配到受管缓存；新 U_clearpath-warehouse 原先已可运行。是否通过重测以矩阵的最新证据为准。历史 H_iris 的旧 SITL FAIL 保留；C01 的新控制 PASS 不会反写为 H_iris 已通过飞行。

## 已修复并保留失败原件

无车会话缺少共用生命周期元数据；首次登录跳转漏 `/simulation`；界面忙碌时请求被忽略；跨浏览器 fault/stop 绕过原控制 owner；STOPPING 报告写入失败遮蔽进程清理；同目录两个 Manager 互相覆盖恢复状态；启动取消后仍发布 READY/RUNNING；运行中状态过期未触发会话退出；动态目标推力过大、缺少阻尼；历史 Fuel 文件 URI 未解析到固定版本缓存。

对应单元、真实 HTTP、原生物理和故障重测与失败原件均保留。冻结遥测时，底层诊断连接本身可能仍显示 connected；Manager 以不可变状态的质量和原采样时间判定过期并退出，不把 connected 当作有效定位。

## 运维边界

资产下载、网格、纹理、日志、签名凭据、EEPROM 与编译结果不进入 Git。每个 Manager 数据目录独占；上游会话持有共享资产使用锁，安装/卸载/替换忙时被拒绝。后台异常重启不会凭磁盘 PID 接管或杀死旧进程，不恢复 SEND；需按原会话日志和已持有的进程证据处理所有权 UNKNOWN。

部分 Fuel 模型元数据包含 CC BY-NC / CC BY-NC-ND，详细来源和许可证在锁清单与场景目录。缓存未作为项目产物重新分发；仓库许可证不能代替每个模型的许可记录。软件资产检查无法认证第三方模型的视觉质量或真实车辆安全性。

### Rover 停车修复的覆盖范围

固定版本 `b3e820a` 的完整 Rover 复跑出现 `stop_exit_deadline_unconfirmed`，原件在
`frozen-regression/rover/`。定向修复只对标准 Rover Goto 增加与已有连续控制一致的
零流 + 原生 HOLD 制动；分别要求停车和模式确认，原阈值、8 秒退出期限和 2 秒稳定窗不变。
`rover-hold-regression/run-1`、`run-2` 两轮完整 Chrome/HTTP/SITL 闭环通过；
Goto 后保持 HOLD，后续运动需显式切换 GUIDED。原有多步自定义 Mission 需要遵守此
明确后置模式；仓库提供的物理 Mission 已另行回归。旧 RViz 报告的其他任务超时
和真实硬件范围没有随此修复获得认证。

R05/C06 的动态目标已连续观察 60 秒接地且未离开测试区域，但施力型控制并不保证
精确沿航点轨迹运动；不把目标范围内运动当作路径跟踪精度验收。
