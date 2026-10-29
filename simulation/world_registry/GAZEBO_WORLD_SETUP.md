# Gazebo 场景库：本机操作

本轮为部分验收。`catalog.yaml` 是 JSON 语法的 YAML；第三方入口、网格及本机日志放在 `assets/` 与 `evidence/`，不提交到 Git。固定版本见清单。不要修改已有上游目录或系统环境。

```sh
cd /home/level6/vehicle-autonomy-framework
python3 simulation/world_registry/fetch.py
# 以下 Fuel 命令下载当前版本；须核对所得版本与资源清单一致，再生成适配副本：
mkdir -p simulation/world_registry/assets/fuel
export GZ_FUEL_CACHE_PATH="$PWD/simulation/world_registry/assets/fuel"
gz fuel download -u 'https://fuel.gazebosim.org/1.0/OpenRobotics/models/ground%20plane'
gz fuel download -u 'https://fuel.gazebosim.org/1.0/OpenRobotics/models/jersey%20barrier'
python3 simulation/world_registry/prepare_playpen.py
python3 simulation/world_registry/worldctl.py list
python3 simulation/world_registry/worldctl.py check iris
python3 simulation/world_registry/worldctl.py launch iris --headless
python3 simulation/world_registry/worldctl.py smoke iris --seconds 60 --timeout 240
```

`fetch.py` 下载指定入口、许可证、果园直接网格及列出的 Playpen 子模型，跳过已存在文件；它不获取 Fuel 资源，也不验证已存在文件的哈希。`check` 调用 `gz sdf -k` 并检查入口内直接引用的 `model://` 网格；不保证递归网格、纹理或远程 Fuel 完整。Gazebo 的资源路径与 SDF_PATH 在子进程中设置；默认指向本机 `/home/level6/gz_ws/src/ardupilot_gazebo` 的模型和插件，可通过原有环境变量补充。运行日志保存在 `simulation/world_registry/evidence/`。`smoke` 的 PASS 仅表示采集到规定仿真时间，须人工核查日志、资源和物理结果，不能代表 SITL 或车辆通过。每次使用独立 Gazebo partition；结束或中断时仅清理该命令创建的进程组。城市街区已单独验证 Gazebo reset 服务；其他场景的 reset 服务尚未验证，也可结束并重新启动。

`launch ID --vehicle MODEL --pose 'x y z roll pitch yaw'` 在临时世界副本中添加模型，属于试验性功能；不启动 SITL，不保证出生点安全，不为已包含车辆的世界去重。请勿同时将多个默认端口的 ArduPilot 插件接入同一 SITL。需要飞控控制时使用框架已有隔离仿真和双 SEND 安全边界，不连接硬件。

ROS 2 Jazzy 位于项目用户级目录，可用 `scripts/with_ros2.sh`；当前 `ros_gz_sim` 与 `ardupilot_gz_bringup` 不在该环境包列表中。ArduPlane 二进制未见于默认 `ardupilot/build/sitl/bin`。完整结果和限制见矩阵与兼容性报告。

Playpen 适配脚本在 `assets/adapter_models` 生成副本，把两个 Fuel URL 指向本地已下载模型，不修改原始文件。由于 SITL_Models 仓库顶层未发现许可证，本轮只保留本地副本，重新分发前须核实具体资源授权。

仓库依赖的 Fuel URL 清单见 `evidence/warehouse-fuel-urls.txt`；将清单中的模型下载至同一个隔离缓存并确认版本后运行 `python3 simulation/world_registry/prepare_warehouse.py`。仓库适配修正 Fuel table v4 的重复 visual 名称和旧版重力字段，且不改上游。
