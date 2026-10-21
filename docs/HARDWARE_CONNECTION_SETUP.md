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
