# 场景资源与版本清单

资源位于本机 `simulation/world_registry/assets/`，由 `.gitignore` 排除；运行记录在 `evidence/`。逐文件 SHA-256 与大小见本机 `evidence/asset-manifest.json`，这是运行时快照，不含之后新增的文件。原始文件和适配副本分开，未写入现有插件源码。

| 资源 | 固定版本 | 许可与注意 |
|---|---|---|
| ArduPilot Gazebo 的 Iris / Zephyr、已有模型与插件 | `3ec51428fd43deb7b71137192ba16394b450d78e` | 仓库 LICENSE 为 LGPL-3.0，具体资源需另核对；本机原有构建 |
| ArduPilot ROS 2 Gazebo 的 Playpen / Multiagent 启动参考 | `8df4dc1726e37504e6fc8b952d02e554cfa3176f` | GPL-3.0，launch 文件仅作为参考 |
| ArduPilot SITL_Models 的 Playpen 及障碍物 | `25bc38ed8c6c0345840159a8cbc0b02781d52f3c` | 仓库顶层未发现 LICENSE；各资源授权未确认，禁止将此视为可再分发许可 |
| Clearpath Simulator 仓库与果园 | `a7c5cf377027cbbb6cb64e4eae9c786750b5b276` | BSD-3-Clause；依赖的 Fuel 模型有各自授权 |
| World Collection 城市 | `a0c262a497da1b0b9fd9970add6ff346e09afaeb` | 该世界 LICENSE 为 Apache-2.0 |
| PX4 Gazebo Models 风场 | `e5997f455e33ec071c7c677fc59a65781de496a4` | BSD-3-Clause；未使用 PX4 飞控 |

Fuel 模型本轮缓存版本：OpenRobotics ground plane 5、jersey barrier 6、warehouse 5、chair 3、foldable_chair 3、MaleVisitorOnPhone 2、table 4；MovAi shelf 1、shelf_big 2；plateau Casual female 1。各模型许可证必须单独核验；不要假定与引用它们的仓库相同。下载时以隔离的 `GZ_FUEL_CACHE_PATH` 保存。资源约数百 MB，重复的适配副本占用额外空间。`fetch.py` 固定 Git 提交但不自动下载 Fuel；`prepare_playpen.py` 和 `prepare_warehouse.py` 只修改本地生成副本。
