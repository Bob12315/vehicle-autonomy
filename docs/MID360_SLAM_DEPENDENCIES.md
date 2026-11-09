# MID-360 目标二依赖与构建记录

此文描述可选仿真工作进程的依赖；不代表目标二整体验收已通过。
正常启动不下载安装依赖，不读取历史 artifacts 作为软件输入，不启动 Livox
SDK、串口、真实雷达驱动或物理雷达网络。所有外部源码、库和大型扫描模式
放在检出之外，HostEnvironment 的 `mid360_slam_root` 指向其根目录（下称 B）。
机器配置只写忽略的 `environments/tools.local.toml`，模板不写本机路径。

## 锁定版本及许可证

完整 commit 见 `simulation/dependencies/mid360-slam.lock.json`：

| 组件 | 用途 | 许可证记录 |
|---|---|---|
| Ericsii/FAST_LIO_ROS2 | Jazzy 上的激光惯性里程计 | 根 LICENSE 为 GPL-2.0；源文件保留其 BSD 通知 |
| hku-mars/ikd-Tree | FAST-LIO 动态树子模块 | GPL-2.0 |
| mathaimp/livox_gz_sim | 实际 Gazebo GPU 图像和 IMU 输入 | MIT；扫描模式保留上游通知 |
| Livox-SDK/livox_ros_driver2 | 仅 CustomMsg / CustomPoint 原始接口 | MIT；不构建 SDK / 硬件驱动 |
| perception_pcl / pcl_msgs | 仅 pcl_conversions 和消息 | BSD-3-Clause |
| GTSAM 4.2.0 | 回环位姿图求解 | BSD-2-Clause；随附第三方通知另行保留 |
| taehun-kmu/SC_PGO | Scan Context、ICP 回环与图优化 | BSD-3-Clause |
| FAST_LIO_LOCALIZATION2 | 已有地图的成熟 ICP 匹配 | GPL-2.0 |
| Open3D 0.19.0 | 上述重定位模块的配准依赖 | MIT |

Python 显式工作进程环境的版本约束见 `python-slam.constraints.txt`；Ubuntu
24.04 x86_64 的构建包版本及 deb SHA256 见 `ubuntu-noble-build.lock.json`。
源码中没有提交第三方二进制或大资源。

## 外部目录准备

按锁文件分别克隆和检出固定 commit，准备以下 B 内目录：

```
ws/src/FAST_LIO_ROS2             # 递归固定 include/ikd-Tree
ws/src/livox_gz_sim
livox-message-source
ws/src/livox_ros_driver2         # 仅接口构建目录
ws/src/perception_pcl
ws/src/pcl_msgs
ws/src/sc_pgo
gtsam-source
relocation-upstream
relocation-runtime              # 同一重定位 commit 的 I/O 适配检出
deps/debs
deps/root
build-venv
```

给对应检出应用 `simulation/dependencies/patches/` 中补丁。构建入口核对
HEAD 和实际完整 diff；未记录的修改会拒绝构建，不只核对 Git 的 HEAD。
接口目录使用 `simulation/dependencies/livox-interfaces/` 两个构建文件，复制原始两个 `.msg` 及 LICENSE，使用 `ament_cmake`、
`rosidl_default_generators`、`std_msgs` 生成类型；不得复制或构建驱动执行程序。
构建入口逐字节核对两个消息仍与固定原始检出一致。

构建依赖可从已验证的软件源下载锁文件所列 deb，并校验 SHA256 后用
`dpkg-deb -x` 解到 `B/deps/root`。这次构建未写 `/usr`，未安装系统服务。
主机已有同版本 VTK 运行库只通过 B 内链接使用，链接目标和哈希保存在
外部 `deps/system-library-links.json`；新主机应重新验证其版本，不能盲目复用。

创建外部系统包可见的 Python 虚拟环境，按约束安装 colcon、Open3D 及其依赖。
框架本身以 editable、`--no-deps` 安装到该工作进程环境，供重定位启动器使用；
框架主环境继续使用仓库规定的 `.venv`，不向系统 Python 安装包。

## 编译

先单独构建并安装 GTSAM 到 B 内：

```
cmake -S "$B/gtsam-source" -B "$B/gtsam-build" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$B/gtsam-install" \
  -DCMAKE_PREFIX_PATH="$B/deps/root/usr" -DGTSAM_USE_SYSTEM_EIGEN=ON \
  -DGTSAM_WITH_TBB=OFF -DGTSAM_BUILD_TESTS=OFF \
  -DGTSAM_BUILD_EXAMPLES_ALWAYS=OFF -DGTSAM_BUILD_UNSTABLE=OFF \
  -DGTSAM_BUILD_WITH_MARCH_NATIVE=OFF
cmake --build "$B/gtsam-build" -j2
cmake --install "$B/gtsam-build"
```

配置 HostEnvironment 后，从仓库显式执行：

```
.venv/bin/python -m vehicle_autonomy.app.bootstrap.build_mid360_slam sensor
.venv/bin/python -m vehicle_autonomy.app.bootstrap.build_mid360_slam fast_lio
.venv/bin/python -m vehicle_autonomy.app.bootstrap.build_mid360_slam pgo
.venv/bin/python -m vehicle_autonomy.app.bootstrap.build_mid360_slam relocalization
```

入口使用 ROS 2 Jazzy 环境、外部前缀、C++17、顺序 colcon 构建及明确 RPATH。
每个 feature 有独立证书，记录该次成功构建的 commit、补丁和产物 SHA256；
只构建一个 feature 不会替其他尚未重建的产物背书。运行前再次核对证书。
overlay 必须通过其 `setup.bash` 加载；继承基础 ROS 的
`COLCON_CURRENT_PREFIX` 后直接调用 overlay `local_setup.bash` 会遗漏类型支持。
系统 Gazebo 服务使用其自身 ABI 优先顺序，避免 ROS vendor Gazebo 库覆盖。

## 补丁边界

- Gazebo：每传感器私有 ROS Context / Domain、显式仿真时钟、400 深度 IMU
  传输缓存，以及从原渲染回调输出的采集事件/实际返回数量。零返回切片保留
  真实采集事件，不生成替代点。没有修改射线几何、图像采集时间和传感器物理值。
- FAST-LIO：Jazzy 构建依赖、日志写入自有 cwd、关闭时不写位置日志、400 深度
  IMU 订阅，以及只读输入时间诊断。诊断发布实际接收的原始 IMU stamp；不生成
  IMU 样本，不改时间偏移、滤波状态、去畸变、迭代更新或配准数学。框架再把
  这些原始 stamp 与原始 CustomMsg 五个实际采集时刻独立配对；回调观察器漏收
  不能被当成算法漏收。五次真实采集须有完整事件证据，实际保留的点和输出位姿
  须有 IMU 覆盖；无证据或不完整时间覆盖的扫描不准入，并计入丢帧。
- SC-PGO：去掉未使用的构建依赖，阻止同一关键帧被定时器重复加入相同回环
  候选，输出实际优化修订和已应用约束数量，为历史地图保留最后采集时间。
  不修改 Scan Context、ICP 或 GTSAM 的求解公式；关闭其 TF 发布及当前位置
  时间戳覆盖，不接入 GPS。
- 重定位：去掉不使用的转换模块导入，并暴露上游已有的配准质量结果；
  crop、体素处理、粗细两次 ICP 和 fitness gate 复用固定上游实现。框架子类
  负责消息转换、精确同 stamp 配对、粗略初值、质量与过期拒绝，不发布 TF。
  输入使用框架已准入的配准点云及同 stamp 的规范化车体 PoseStamped，不再重复
  应用 IMU 外参。有效匹配由唯一 LIO Adapter 按原采集 stamp 发布
  `saved_map → local_map → odom → base → lidar`，不延长旧 TF 的时间。

版本固定和编译成功只是依赖资格，不能替代实际运动、地图、重定位和生命周期
验收。各项结果及失败修复须以目标二验收报告和原始记录为准。
