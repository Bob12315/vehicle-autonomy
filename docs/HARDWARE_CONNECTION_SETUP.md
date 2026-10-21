# 当前接线与环境配置

2026-10-21。以下为本次接线后的实际检查，补充旧版硬件审计；不覆盖 P26 FAIL，
不构成实车运动或安全验收。真实飞控全程只接收，未修改参数、请求模式或解锁。

| 链路 | 实测结果 |
|---|---|
| 电脑 enp2s0 → RK3588 eth1 | 192.168.50.1/24 → 192.168.50.2/24，SSH 正常 |
| RS16 → RK3588 eth0 | 两端有链路；最初仅 ARP，无 UDP，接收 IP 不匹配 |
| 雷达网络修复 | 抓包实测源 192.168.1.200 请求接收端 192.168.1.181；只在 eth0 添加 192.168.1.181/24 并持久保存，保留 192.168.10.15/24、管理口及路由 |
| RS16 UDP | 实测 MSOP 6699 / DIFOP 7788，每包 1248 字节 |
| 官方 SDK / ARM64 实时解码 | 18 秒 180 帧；末帧 3456 个有效 XYZ 点；8 秒原始抓包 5890 包，内核报告丢包 0 |
| 飞控 USB → 电脑 | MicoAir743v2 稳定设备 ID，收到 ArduPilot Rover 心跳/姿态，16 秒 11588 字节，发送 0 字节 |
| 飞控当前质量 | 未解锁，custom_mode=4/HOLD；报告 Radio Failsafe / PreArm: Radio failsafe on；未收到 GPS_RAW_INT / EKF_STATUS_REPORT，位置经纬度为 0，不能用于导航 |
| 罗盘 | 用户报告未校准，留待户外人工完成；未关闭检查或修改参数 |
| 时钟 | 板端落后电脑约 130240 秒；从已 NTP 同步的电脑经 SSH 单次校时，校正后约 0.2 秒偏差；未写 RTC，采集时钟仍未认证 |

电脑上的 Chicony USB 摄像头是电脑设备；板端 ISP video 节点不等于已接入真实相机。
当前飞控接在电脑，机载应用不会把它标成已直连；移动运行前仍需确定实际飞控数据链。
遥控失联原因需结合遥控器供电/接收机现场检查，不能通过禁用 failsafe 消除。

## 重复只读检查

在仓库根目录运行；若地面站占用串口，先关闭占用程序再运行，不与其争用设备：

```bash
PYTHONPATH=. python scripts/diagnose_rover_readonly.py \
  --port /dev/serial/by-id/usb-ArduPilot_MicoAir743v2_260029000C51333238373537-if00 \
  --duration 20 --report artifacts/hardware-ready/fc-latest.json
```

软件连接通过只代表收到新鲜 Rover 心跳；GPS/EKF/校准和实车验收另列。

## 接收进程监管

`deployment.onboard --rs16-config /absolute/rs16.json` 会监管官方 SDK、只读 Application
和认证 Web；`--ros2-humble` 增加隔离 ARM64 ROS 侧车。任一子进程退出都会关闭整栈，
需要明确重启。SDK 每次新 epoch，接收时间和序号不通过轮询刷新。默认不启动任何
设备，默认 SEND 保持 false。SDK 持续时间最多 86400 秒，结束后整栈关闭。

监管器记录 boot ID 与自己实际观察到的 socket inode。重启后只回收已证明属于
上一 boot 的同一 inode；未知文件或其他进程的 socket 保持拒绝覆盖。

后续安装及实测结果继续记录于本文件；完整日志在
`artifacts/hardware-ready/connection-20261021/`，原始硬件抓包不能作为合成夹具替换。

## 板端隔离环境与实际验证

ROS 2 Humble、完整 navigation2/nav2_bringup、robot_localization、SLAM Toolbox、
rosbag2 与 libpcap 开发文件以 626 个经 APT 签名/索引哈希验证的 ARM64/all 包提取到
`/home/pi/vehicle-autonomy/ros2-humble/root`。没有在系统执行 apt install、维护脚本、
全局 Python 安装或替换已有系统库；venv 使用板端 Python 3.10。Humble 的本地
wrapper 单独设置库/包路径，限制 ROS 为 localhost/domain 85。

目标系统原 ICU 来自 proposed，稳定仓库 dev 版本不匹配。首次依赖解析失败日志
保留；改为在独立 prefix 中同时使用稳定 ICU runtime/dev，原系统 ICU 保持。
SLAM 初次加载找不到位于 `usr/lib` 的 Ceres，已修复 wrapper 路径，实际 Ceres
solver 加载成功。Humble 默认 SIGTERM 导致回调中 context 提前关闭，已改为信号
仅设置退出标记；实际接收中的 SIGTERM 验证退出码 0、无 traceback。

- 真实 SDK → PointCloud2/LaserScan：20 秒各 200 帧，均 10 Hz；有效点
  3645–3778/帧，扫描已知 bins 305–317/720；最大 ROS 源年龄 207.907 ms，
  0 错误、源 epoch 单一、发布者均为 vaf_rs16_scan。未知角度保持 NaN。
- 实际 ARM64 官方 SDK PCAP 回放：8 秒真实录制输入解码 78 帧，退出码 0；
  标记 pcap_replay，未冒充 live。PCAP-enabled 二进制保存在 rs16-build-pcap。
- Nav2 planner_server 创建生命周期节点/代价地图后受控关闭；SLAM 实际加载
  solver_plugins::CeresSolver 后受控关闭。这是原生依赖运行检查，不是导航/建图验收。
- 原板端 Jazzy/x86 库未复用，PC Jazzy 合成测试仍接受 6 帧、拒绝 2 帧。
- PC 全量 287 测试、板端非 Gazebo profile 258 测试通过，均 0 跳过。

默认应用采样周期改为本地配置的 50 ms，以避免与 10 Hz 最新点云恰好同频。
应用的 dropped_clouds 是读取最新文件时跳过的 SDK 序号，不能解释为 UDP 网络
丢包率；初始 100 ms 配置曾观察到这种跳帧。抓包的 0 dropped 仅指该次内核捕获。

上述 ROS/导航包选择参考 [ROS Humble 官方平台说明](https://docs.ros.org/en/humble/Installation/Alternatives/Ubuntu-Install-Binary.html)
及 [Nav2 官方安装说明](https://docs.nav2.org/rolling/getting_started/quickstart/quickstart/)。

## 已配置的一键操作

板端执行，启动只读 Application、官方 SDK、ROS 点云/扫描、认证 Web：

```bash
/home/pi/vehicle-autonomy/current/scripts/onboard-connected.sh start
/home/pi/vehicle-autonomy/current/scripts/onboard-connected.sh status
/home/pi/vehicle-autonomy/current/scripts/onboard-connected.sh stop
```

不安装开机自启。配置在 `/home/pi/vehicle-autonomy/config/`，跨版本保留；源码
版本目录不混入设备配置。启动不会改网络、设置飞控参数或启动 Nav2 运动节点。

电脑开两个终端维持私有隧道；本次已实际建立，连接结束/重启后需重新运行：

```bash
ssh -NT -L 127.0.0.1:19436:127.0.0.1:11436 bob@10.10.12.240
ssh -NT -L 127.0.0.1:8765:127.0.0.1:8765 \
  -R 127.0.0.1:19436:127.0.0.1:19436 pi@192.168.50.2
```

打开 http://127.0.0.1:8765 ，令牌通过 SSH 读取后输入页面，不写 URL 或 Git：

```bash
ssh pi@192.168.50.2 'cat ~/.local/state/vehicle-autonomy-connected/token'
```

板端重新执行真实数据链检查：

```bash
cd /home/pi/vehicle-autonomy/current
./scripts/with_ros2_humble.sh /home/pi/vehicle-autonomy/venv/bin/python \
  -m integrations.ros2.verify_lidar --exchange /home/pi/vehicle-autonomy/live/cloud.json \
  --provenance live_sdk_system_timestamp --duration 20 --report /tmp/rs16-live-check.json
```

离线依赖复现：从目标复制 `/etc/os-release` 与 `/var/lib/dpkg/status`，在联网电脑
运行 `python scripts/setup_ros2_arm64.py --directory NEW_PRIVATE_DIR --status-file COPY \
--os-release-file COPY`，核验生成 manifest，再传送 root/。初始包和后续增量归档
分别保存 SHA256；不需要给 RK3588 添加默认路由。

## 仍需现场确认

罗盘校准、GPS/EKF 质量、遥控失联原因、雷达刚性安装与 lidar→base_link 外参、
车体/地面过滤、真实相机、物理急停和驱动失能仍未验收。当前不是自主行驶配置。
板端 RTC 报告 2021 年且没有可达 NTP 默认路由；本次只校正系统时间，重启后须
重新检查时间，不能把一次 SSH 校时当持续同步或传感器时间标定。
