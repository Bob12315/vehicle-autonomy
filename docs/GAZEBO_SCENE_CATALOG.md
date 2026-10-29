# Gazebo 场景目录

日期：2026-10-29。当前目录有 **60 个世界入口**：24 个本仓库参数化专项场景、28 个新增上游世界、8 个历史入口；历史 Multiagent 是未安装的 launch 参考，不能计为可运行世界。资产锁有 **39 个条目**：28 个世界、10 个 Fuel 模型、1 个动态对象插件源包。入口数量不等于通过数量。

实际 L1–L6、车型运动成绩、性能、失败及本轮证据，以 [兼容矩阵](GAZEBO_COMPATIBILITY_MATRIX.md)、[测试报告](SIMULATION_TEST_REPORT.md)和[性能报告](SIMULATION_PERFORMANCE_REPORT.md)中对应的 scene_id 为准。本目录的“依赖存在”仅表示文件/插件可解析，不代表已经运行 Gazebo、SITL 或网页验收。

## 场景、世界、车辆和任务分离

`center_catalog.json` 保存专项场景配方；`SceneRegistry.generate()` 只生成环境 SDF，不自动插入车辆或任务。仿真管理器另选受支持的车辆装配，并复用既有 Action / Mission / Execution / Safety / 唯一 MAVLink writer。`vehicles` 是候选车型信息，不能绕过管理器按实际验证限制的组合。

源代码位于 `src/vehicle_autonomy/app/simulation/{catalog,scenarios,assets}.py`；版本化配方与下载锁位于 `simulation/scenarios/center_catalog.json` 和 `assets.lock.json`。模型、缓存、构建产物、私密配置和原始日志不提交 Git。

## 24 个专项场景

共同来源是本仓库原创的程序化工程测试几何，没有第三方网格依赖。版本为 1；许可证记录为本仓库原创场景代码/配方，仓库尚无统一 LICENSE，不额外推定开源许可。每个编号独立生成可启动 SDF；它们不是对原地图的艺术质量复制。范围是水平地面碰撞范围，单位米。

| ID | 中文名称 | World 配方 | 候选车型 | 范围 | 主要实体/限制 |
|---|---|---|---|---|---|
| R01 | 标准驾驶测试场 | procedural-driving | rover | 120 × 120 | 双侧路标、直行通道 |
| R02 | GPS 户外导航场 | procedural-gps | rover | 120 × 120 | 户外路标、GPS坐标原点；GPS故障另行注入 |
| R03 | 城市道路 | procedural-urban | rover | 120 × 120 | 实体建筑、道路 |
| R04 | 仓储物流中心 | procedural-warehouse | rover | 120 × 120 | 实体货架、侧墙和屋顶 |
| R05 | 动态交通区 | procedural-traffic | rover | 120 × 120 | 三辆动态方块目标，TrajectoryFollower 实际施力 |
| R06 | 果园与林地 | procedural-forest | rover | 120 × 120 | 带碰撞树干、树冠 |
| R07 | 山坡越野地形 | procedural-slope | rover | 120 × 120 | 实体坡道；越野控制未由地图实现 |
| R08 | 多楼层建筑 | procedural-multilevel | rover | 120 × 120 | 实体楼层、连接坡道；无电梯/多层定位算法 |
| C01 | 开阔飞行场 | procedural-open | copter | 120 × 120 | 开阔地面 |
| C02 | 三维障碍训练场 | procedural-obstacles3d | copter | 120 × 120 | 不同高度实体障碍 |
| C03 | 室内仓库 | procedural-indoor | copter | 120 × 120 | 货架、侧墙、屋顶；不自动提供无GPS定位 |
| C04 | 城市建筑群 | procedural-urban | copter | 120 × 120 | 实体建筑、道路 |
| C05 | 森林和山谷 | procedural-valley | copter | 120 × 120 | 树木和两侧山脊 |
| C06 | 运动目标场 | procedural-moving | copter | 120 × 120 | 三个受力运动目标；无自动跟踪算法 |
| C07 | 视觉降落平台 | procedural-landing | copter | 120 × 120 | 实体降落平台、棋盘图案；无自动视觉降落算法 |
| C08 | 多目标任务场 | procedural-search | copter | 120 × 120 | 六个不同颜色目标；不修改旧CUADC |
| F01 | 标准机场 | procedural-airport | plane | 2000 × 2000 | 500米实体平面跑道 |
| F02 | 大型平原 | procedural-plain | plane | 2000 × 2000 | 大范围平原、跑道 |
| F03 | 丘陵山谷 | procedural-hills | plane | 2000 × 2000 | 实体丘陵坡道、跑道 |
| F04 | 农田村庄 | procedural-village | plane | 2000 × 2000 | 村庄建筑、跑道 |
| F05 | 河流桥梁 | procedural-river | plane | 2000 × 2000 | 桥面/桥墩有碰撞，蓝色河面是视觉效果、没有流体 |
| F06 | 风场测试区 | procedural-wind | plane | 2000 × 2000 | Gazebo WindEffects、环境风矢量；AP内部风响应未证明 |
| F07 | VTOL 综合测试场 | procedural-vtol | plane | 2000 × 2000 | 平台、棋盘图案、跑道；没有已验收QuadPlane装配 |
| F08 | 空地协同测试区 | procedural-cooperative | plane | 2000 × 2000 | 空地集合目标区、跑道；多车控制/通信隔离需另测 |

生成示例（在已安装的隔离环境中）：

```python
from pathlib import Path
from vehicle_autonomy.app.simulation.catalog import SceneRegistry

registry = SceneRegistry()
registry.generate("R05", Path("artifacts/simulation/R05.sdf"), seed=42,
                  parameters={"obstacle_count": 12, "friction": 0.8})
```

| 参数 | 范围 | 实际作用 |
|---|---|---|
| seed | 整数 0…2³²−1 | 固定随机障碍位置与建筑高度，可重放 |
| obstacle_count | 整数 0…80 | 添加有碰撞实体障碍，避开出生区和跑道 |
| wind_speed | 0…20 m/s | 设置 Gazebo wind；只影响支持风的链接，不能据此宣称飞控动力学受风 |
| wind_direction | −180…180° | 水平风向，以世界 X 轴为零 |
| light_intensity | 0…1 | 光照视觉参数，不能冒充物理扰动 |
| friction | 0.1…3 | 地面及随机障碍 SDF ODE 摩擦参数；真实车辆响应仍需实测 |

上述参数会写入 SDF；不支持的字段、非有限值和超范围值会被拒绝。传感器噪声、GPS/IMU故障、车辆网络故障不能靠这个配方静默模拟，必须经过另行支持的模型或软件链路。出生姿态由统一管理器的受控配置处理；固定翼不能使用多旋翼悬停/零速停车语义。

## 新增上游世界与固定版本

所有下列世界及仓库许可证文件均已真实下载并写入 SHA256、字节数和精确提交。Clearpath 的六个世界全部纳入；五个网格世界另下载了完整相关网格/纹理，Warehouse 通过十个固定版本 Fuel 模型缓存复用。World Collection 动态世界还需要已编译的独立插件；源下载和插件编译不等于动态行为验收。

| scene_id | 上游入口 | 固定提交 | 仓库许可证 | 安装状态 | 当前依赖检查 |
|---|---|---|---|---|---|
| U_ardupilot-gimbal | gimbal | 3ec51428fd43 | LGPL-3.0-or-later | 入口/锁定文件已安装 | BLOCKED：资源或插件缺失 |
| U_ardupilot-zephyr-parachute | zephyr_parachute | 3ec51428fd43 | LGPL-3.0-or-later | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_clearpath-construction | construction | a7c5cf377027 | BSD-3-Clause | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_clearpath-office | office | a7c5cf377027 | BSD-3-Clause | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_clearpath-orchard | orchard | a7c5cf377027 | BSD-3-Clause | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_clearpath-pipeline | pipeline | a7c5cf377027 | BSD-3-Clause | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_clearpath-solar-farm | solar_farm | a7c5cf377027 | BSD-3-Clause | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_clearpath-warehouse | warehouse | a7c5cf377027 | BSD-3-Clause | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_collection-f1-maze-s08-perfect-kr | f1_maze_s08_perfect_kr | a0c262a497da | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_collection-f3-aisles-h30x20-a150-x1 | f3_aisles_h30x20_a150_x1 | a0c262a497da | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_collection-f4-forest-s40-d003 | f4_forest_s40_d003 | a0c262a497da | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_collection-f5-urban-w06-b15 | f5_urban_w06_b15 | a0c262a497da | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_collection-mo1-office-strip-moving | mo1_office_strip_moving | a0c262a497da | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_collection-mo2-warehouse-moving | mo2_warehouse_moving | a0c262a497da | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_collection-sc1-square-loop | sc1_square_loop | a0c262a497da | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_gazebo-air-pressure | air-pressure | 43d9baf13eac | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_gazebo-contact-sensor | contact_sensor | 43d9baf13eac | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_gazebo-imu | imu | 43d9baf13eac | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_gazebo-navsat | navsat | 43d9baf13eac | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_gazebo-sensors | sensors | 43d9baf13eac | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_gazebo-shapes | shapes | 43d9baf13eac | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_gazebo-trajectory-follower | trajectory_follower | 43d9baf13eac | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_gazebo-wind | wind | 43d9baf13eac | Apache-2.0 | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_px4-forest | forest | e5997f455e33 | BSD-3-Clause | 入口/锁定文件已安装 | BLOCKED：资源或插件缺失 |
| U_px4-frictionless | frictionless | e5997f455e33 | BSD-3-Clause | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_px4-moving-platform | moving_platform | e5997f455e33 | BSD-3-Clause | 入口/锁定文件已安装 | BLOCKED：资源或插件缺失 |
| U_px4-ridge | ridge | e5997f455e33 | BSD-3-Clause | 入口/锁定文件已安装 | 依赖存在；运行另验 |
| U_px4-walls | walls | e5997f455e33 | BSD-3-Clause | 入口/锁定文件已安装 | 依赖存在；运行另验 |

来源仓库：[Clearpath Simulator](https://github.com/clearpathrobotics/clearpath_simulator)、[World Collection](https://github.com/mertgulerx/world-collection)、[PX4 Gazebo Models](https://github.com/PX4/PX4-gazebo-models)、[Gazebo Sim](https://github.com/gazebosim/gz-sim)、[ArduPilot Gazebo](https://github.com/ArduPilot/ardupilot_gazebo)。完整提交与逐文件下载 URL 均在 `assets.lock.json`；不依赖浮动 main 分支。

三个最初猜测的 Gazebo 示例路径返回 404，其探测记录保留在锁文件 `failed_source_probes`。随后通过上游树确认真实路径并下载 `test/worlds/{imu,navsat,air_pressure}.sdf` 和 `examples/worlds/sensors.sdf`，没有用空文件代替缺失示例。

## Fuel 与旧格式适配

Fuel 引用由受信清单将原别名映射到明确版本，再解析到校验后的本地模型。未知版本或未锁定资源保持 BLOCKED，运行时不自动追踪 latest。`AssetManager.install()` 会安装锁中 `requires` 依赖；可检查状态、完整性、卸载并保留共享内容缓存。失败/取消不会覆盖上一份完整安装。

| Fuel 模型 | 固定版本 | 对应版本元数据中的许可证 |
|---|---|---|
| fuel-movai-shelf-big-2 | 2 | Creative Commons Attribution Non Commercial No Derivatives 4.0 International |
| fuel-movai-shelf-1 | 1 | Creative Commons Attribution Non Commercial 4.0 International |
| fuel-openrobotics-table-4 | 4 | Creative Commons Zero v1.0 Universal |
| fuel-openrobotics-chair-3 | 3 | Creative Commons Attribution 4.0 International |
| fuel-openrobotics-jersey-barrier-6 | 6 | Creative Commons Zero v1.0 Universal |
| fuel-openrobotics-foldable-chair-3 | 3 | Creative Commons Attribution 4.0 International |
| fuel-openrobotics-warehouse-5 | 5 | Creative Commons Attribution Non Commercial No Derivatives 4.0 International |
| fuel-openrobotics-malevisitoronphone-2 | 2 | Creative Commons Attribution 4.0 International |
| fuel-openrobotics-ground-plane-5 | 5 | Creative Commons Zero v1.0 Universal |
| fuel-plateau-casual-female-1 | 1 | Creative Commons Zero v1.0 Universal |

许可证元数据于 2026-10-29 从 Fuel 读取，且元数据版本与锁定模型版本一致；各项 `license_url` 和 `license_source` 在锁文件内。部分资源为非商业或禁止衍生分发的许可，下载到本地测试缓存不等于有权再分发。原资源、模型和纹理没有加入本仓库 Git。

生成新副本时进行明确的兼容适配：把旧 `physics/gravity` 移到 `world/gravity`；为同一链接中与 collision 重名的 visual 改名；只在已有 PBR/diffuse 替代时移除可选 Classic `gazebo.material` 脚本；把可解析资源和嵌套 include 重定位到本地固定文件。保留原下载文件和哈希，不把未知 Classic 插件当作 Harmonic 插件。模型根据 `model.config` 选择 Harmonic 支持的最高 SDF 版本。

## World Collection 动态对象插件

上游源码版本 `a0c262a497da1b0b9fd9970add6ff346e09afaeb`，Apache-2.0。构建使用其原 CMake 配置，最多两个编译任务，实际链接 `libgz-sim8.so.8`、`gz-transport13` 与 `gz-msgs10`；`ldd` 无缺失库。原始构建日志、二进制哈希和源码版本证据在 `artifacts/simulation/center-20261029/source-plugin-build/`。实际 Gazebo 动态行为等级仍以最终矩阵为准。

重建方法（源码先由受信资产管理器安装）：

```bash
cmake -S "$VAF_SIM_ASSET_CACHE/installed/collection-moving-objects-plugin" \
  -B "$VAF_SIM_ASSET_CACHE/build/collection-moving-objects-a0c262a497da" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$VAF_SIM_ASSET_CACHE/build/collection-moving-objects-a0c262a497da" -j2
```

启动前还要记录 `build-manifest.json`（source_version、binary_name、binary_sha256、gz_sim_major=8）。只有源码哈希、二进制哈希和该 manifest 均匹配，`AssetManager.plugin_paths` 才公布插件目录；管理器将其加入该次自有 Gazebo 的插件搜索路径。通过网页登录不能提交构建命令或任意插件路径。

## 历史八个入口

保留 `simulation/world_registry/` 原目录及历史报告。此前七个世界有 60 仿真秒推进证据；第八个 Multiagent 只是 ROS launch 参考。历史 Iris 的 SITL/Framework 运动尝试失败，不因此宣称已通过飞行。新一轮结果使用独立 session/证据，不覆盖这些失败。

| scene_id | 中文名称 | 入口是否存在 | 既有证据（不计本轮 PASS） |
|---|---|---|---|
| H_playpen | Rover 游乐场 | 是 | 60 s headless simulation time advancement; see matrix |
| H_iris | Iris 跑道 | 是 | 60 s headless simulation time advancement; see matrix；IMU and stationary scene NavSat sample |
| H_zephyr | Zephyr 跑道 | 是 | 60 s headless simulation time advancement; see matrix |
| H_warehouse | 仓库 | 是 | 60 s headless simulation time advancement; see matrix |
| H_urban | 城市街区 | 是 | 60 s headless simulation time advancement; see matrix；one reset service test；Rover model loaded briefly; physical acceptance incomplete |
| H_orchard | 果园 | 是 | 60 s headless simulation time advancement; see matrix |
| H_windy | 风场 | 是 | 60 s headless simulation time advancement; see matrix |
| H_multiagent | 多车辆 | 否 | 未验证 |

历史来源/提交/许可还保留在 `simulation/world_registry/catalog.yaml`。历史目录可能引用本机外部的 Gazebo 模型；缺少这些依赖的安装会准确显示入口存在但启动 BLOCKED。wheel 只携带目录元数据，不携带主机资产或历史日志。

## 资源位置与复现

显式构造参数 `asset_cache` 优先，其次是受信进程环境 `VAF_SIM_ASSET_CACHE`。源码工作区默认复用 `simulation/world_registry/assets/center-source`；安装 wheel 时默认使用 `$XDG_CACHE_HOME/vehicle-autonomy/simulation-assets` 或 `~/.cache/vehicle-autonomy/simulation-assets`，不会向只读 share 安装目录写入。浏览器不能选择任意路径或下载 URL。

```python
from vehicle_autonomy.app.simulation.catalog import SceneRegistry
r = SceneRegistry()
print(r.assets.status("clearpath-office"))
r.assets.install("clearpath-office")
r.generate("U_clearpath-office", "artifacts/simulation/office.sdf")
# 如不再需要：r.assets.uninstall("clearpath-office")
```

统一仿真/回归入口、登录和实际按键操作参见 [Simulation Manager API](SIMULATION_MANAGER_API.md) 与 [仿真中心使用说明](SIMULATION_WEB_UI_GUIDE.md)。性能必须引用对应真实会话采样；未采集的 GPU、传感器或碰撞数据应显示未知。
