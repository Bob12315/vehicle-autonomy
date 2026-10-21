# ROS 2 导航工具与 Web 任务台

2026-10-21，按用户新的职责划分调整。Web 显示任务、状态和业务信息；地图和
空间数据使用 ROS 2 原生工具。该调整不代表实车导航准入通过，P26 原有失败、
定位/外参及物理安全门槛继续有效。

| 功能 | 负责工具 | 当前状态 |
|---|---|---|
| 任务选择、启动/取消、结果、日志、AI 提案 | Web → Application API | 已运行；实车保持只读，没有可执行 Mission catalog |
| 点云、扫描、地图、TF、路径和代价地图显示 | RViz2 | 提供两个只读配置；PC Jazzy / 板端 Humble 原生程序加载检查另记证据，GUI 画面需实际图形会话确认 |
| 录制与回放 | ros2 bag | 真实 RS16 录放已验证，明确区分 live 与 replay |
| 建图、地图保存/加载、重定位 | SLAM Toolbox / Nav2 Map Server / AMCL | 原生依赖已运行；真实外参、里程计/地图定位质量尚未准入 |
| 全局规划、局部控制、重规划 | Nav2 | 已有受控只读规划适配；完整实车控制建议适配和验收尚未完成 |
| 运动授权与最终写入 | Application / Typed Effect / Safety / Lease / 唯一 writer | 保留原边界；当前硬件无 writer，不打开 SEND |

Web 已移除地图画布、点选航点和地图保存/加载按钮；保留传感器健康摘要、摄像头、
任务选择、取消请求、日志、报告和 AI 提案。历史只读地图/草稿 API 保留兼容既有
工具与验证，不能产生车辆运动。不会为替换 UI 修改 Core、冻结合同或旧归档。

## 当前查看真实 RS16

板端 SDK/ROS 在 localhost、ROS_DOMAIN_ID=85 发布：

- `/vaf/lidar/points`：PointCloud2，frame `lidar`。
- `/vaf/lidar/scan`：LaserScan，frame `lidar`，无回波方向为未知。

在 RK3588 自己的图形终端执行：

```bash
cd /home/pi/vehicle-autonomy/current
./scripts/ros2_view.sh lidar
```

也可在有 X11 图形会话的电脑显式转发板端窗口：

```bash
ssh -X pi@192.168.50.2 \
  'cd /home/pi/vehicle-autonomy/current && ./scripts/ros2_view.sh lidar'
```

ROS 进程仍运行在板端，X11 转发窗口。图形/GL 支持须实际确认；本轮原生 `--help`
与软件配置检查不能冒充 RViz 画面验收。没有替用户更改 SSH 服务或管理网卡。
仅打开 `http://127.0.0.1:8765` 的 SSH 隧道不会转发 ROS DDS。电脑 Jazzy 与板端
Humble 的跨版本 DDS 不默认认定可用，也没有自动扩大 ROS 网络发现范围。

`lidar` 配置固定坐标系为 `lidar`，只显示雷达自身坐标，无虚构的 base_link 外参。
可用以下命令检查 RViz2 本体/Qt 依赖；不需要图形桌面，也不会启动导航：

```bash
./scripts/ros2_view.sh lidar --check
```

## 地图和规划显示

在运行已验证地图与 TF 数据源的 ROS 主机上：

```bash
./scripts/ros2_view.sh navigation
```

该配置读取 `/map`、`/tf`、`/plan`，可选显示 `/global_costmap/costmap` 与
`/local_costmap/costmap`。固定坐标系为 `map`。当前硬件没有合格 map→odom→base_link
链，此视图会缺数据；这应通过真实标定与定位解决，不能发布假静态 TF 消除报错。
现有私有 planner job 使用自己的 namespace/frame，并不自动变成公共 `/plan`。
将其显示到公共导航图需要显式、保留 frame/epoch 的诊断适配，本次未假装已有该输出。

两个配置均只带相机移动、选择和聚焦工具，没有 Nav2 Goal、初始定位发布或车辆
控制面板。未来 RViz 点选目标应作为目标提案进入 Application，经过地图/车辆会话
校验、任务注册和实车人工授权后执行。标准 RViz/Nav2 Goal 不能绕过此边界。

## Nav2 接入边界

目标分工为：

```text
ROS 工具选择目标 / Web 选择已注册任务
          ↓
Application：目标校验、任务编排、批准与取消
          ↓
Nav2：规划 / 局部控制建议
          ↓
受控 Navigation Adapter → Typed Effect → Safety / Lease → 唯一 writer → 飞控
```

Nav2 的标准局部控制器会生成速度命令，见
[Humble Controller 官方说明](https://api.nav2.org/nav2-humble/html/md_nav2_controller_README.html)。
未来适配须将其隔离为候选输入，绑定车辆会话、任务 lease、源时间与期限，拒绝
旧会话/重复/超时/不合格定位，并保留独立碰撞保护和停止确认。不能把 `/cmd_vel`
直接连接 MAVLink 或 STM32/DAC。本次未修改原指导律，未把通用 Nav2 bringup 当作
已实现的实车 Application 集成。

## 环境复现

PC Ubuntu 24.04/amd64 的独立 Jazzy prefix：

```bash
python scripts/setup_ros2_local.py --navigation --visualization
```

板端 Ubuntu 22.04/ARM64 继续使用离线提取；在联网电脑准备：

```bash
python scripts/setup_ros2_arm64.py --directory PRIVATE_PREFIX \
  --status-file BOARD_DPKG_STATUS --os-release-file BOARD_OS_RELEASE --visualization
```

仅提取经签名索引/哈希校验的包，不运行系统安装或维护脚本。RViz2 的私有 Qt 插件
路径仅在显示脚本中设置，不改变应用、相机或 ROS 传感器进程环境。

RViz 显示模型与坐标系语义参考
[官方 RViz 用户指南源码](https://github.com/ros2/rviz/blob/rolling/rviz2/doc/index.rst)。

## 本次验证

Web/LLM 相关 10 项测试通过；JS 语法及合成 DOM/API 冒烟检查通过（只读任务禁用、
仿真任务绑定会话、没有地图请求、摘要不展开点云）。两个 RViz YAML 配置通过检查。
PC Jazzy 与板端 Humble 的 RViz2 实际执行 `--help` 成功；ARM 初次缺少 Qt 平台插件，
在显示脚本显式设置独立 prefix 的插件路径后通过，原失败日志保留。ARM 增量仅新增
一个 RViz2 包，独立 prefix 共 627 包；系统包与 ROS 网络发现配置未修改。

图形渲染和显示效果仍未验收，不能把原生帮助输出当作 RViz 画面通过。原始日志与
文件哈希见 [`autonomy/evidence/ros-tools.json`](autonomy/evidence/ros-tools.json)。
