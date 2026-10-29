# Gazebo 场景兼容与验收矩阵

> 2026-10-29 通用车辆组合阶段已继续更新。当前固定模型、多车、跨 World 和原生/Web 验收以 [通用仿真报告](UNIVERSAL_SIMULATION_TEST_REPORT.md) 为准；本页旧轮次数字保留为历史证据。
日期：2026-10-29（Asia/Ulaanbaatar）。Copter/Plane 的固定版本原生/Chrome 回归在 `b3e820a` 执行；Rover 此次复跑失败后补上原生 HOLD 制动，并完成两轮完整成功重测。最终实现提交见机器索引，失败原件保留。60 是目录入口数，其中包含历史 launch 参考，不等于 60 个独立可运行世界。

| 等级 | PASS | FAIL | BLOCKED | NOT_TESTED |
|---|---:|---:|---:|---:|
| L1 | 56 | 0 | 4 | 0 |
| L2 | 56 | 0 | 4 | 0 |
| L3 | 3 | 0 | 0 | 57 |
| L4 | 3 | 0 | 0 | 57 |
| L5 | 3 | 0 | 0 | 57 |
| L6 | 3 | 0 | 0 | 57 |

L1 为 SDF/资源与插件入口检查；L2 为真实无头 Gazebo 时间推进和必需加载错误扫描。L3–L6 只对 R01/Rover、C01/Iris Copter、F01/Twin Cessna 的指定参数组合计 PASS；不是所有候选车型、种子或扰动的交叉认证。R05/C06 的独立 60 秒重力/接触/动态对象探测是物理子集，不提升为完整车辆 L3。

| ID | 名称 | 入口已安装 | L1 | L2 | L3 | L4 | L5 | L6 | 最新证据 |
|---|---|---|---|---|---|---|---|---|---|
| R01 | 标准驾驶测试场 | 是 | PASS | PASS | PASS | PASS | PASS | PASS | `artifacts/simulation/center-20261029/rover-hold-regression/run-2/result.json` |
| R02 | GPS 户外导航场 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-51ac2dafdc0a498aaccc57342f142f18/smoke-result.json` |
| R03 | 城市道路 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-348b53756b0048e4b0aa6725e8c672af/smoke-result.json` |
| R04 | 仓储物流中心 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-8786618c18bd4400b57898b2457a4254/smoke-result.json` |
| R05 | 动态交通区 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/postfix-worlds/sim-1123c4642aea4203bf2b203ca218b164/smoke-result.json` |
| R06 | 果园与林地 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-fc205dd5f4a64b5da9156c9e4c6476f2/smoke-result.json` |
| R07 | 山坡越野地形 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-50679fce5f9943e28ab01735ac6e0fb5/smoke-result.json` |
| R08 | 多楼层建筑 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-b6664fc08d604ea0a035b9236dd91b21/smoke-result.json` |
| C01 | 开阔飞行场 | 是 | PASS | PASS | PASS | PASS | PASS | PASS | `artifacts/simulation/center-20261029/frozen-regression/copter/result.json` |
| C02 | 三维障碍训练场 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-90c571b973dc4b85bcf8f9be1307d5fe/smoke-result.json` |
| C03 | 室内仓库 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-321887348e5a4cafbfa11c482566d04a/smoke-result.json` |
| C04 | 城市建筑群 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-7725a3619c54485190c67c27a108137c/smoke-result.json` |
| C05 | 森林和山谷 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-c90fb49ff1ba48a4ab9951921158368e/smoke-result.json` |
| C06 | 运动目标场 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/postfix-worlds/sim-63df3b4ddb13471d89107d9366730809/smoke-result.json` |
| C07 | 视觉降落平台 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-59f71d40be924e77bebd450c57ee8cc6/smoke-result.json` |
| C08 | 多目标任务场 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-46b77eb1fde4426b8635862298f5b712/smoke-result.json` |
| F01 | 标准机场 | 是 | PASS | PASS | PASS | PASS | PASS | PASS | `artifacts/simulation/center-20261029/frozen-regression/plane/result.json` |
| F02 | 大型平原 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-8a05707305ae4b79aeab1736c6b4bede/smoke-result.json` |
| F03 | 丘陵山谷 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-d5fac75da8d443c09ebb82a3825723bb/smoke-result.json` |
| F04 | 农田村庄 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-ffaf35003d59482393bc269056b833e0/smoke-result.json` |
| F05 | 河流桥梁 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-e44b461c7b314fcd8a3e56585a587979/smoke-result.json` |
| F06 | 风场测试区 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-bd7b15c044cc4e8fb5c21ac10bb671cd/smoke-result.json` |
| F07 | VTOL 综合测试场 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-cc5129d5ed3b40ceb30ae82f8299bb1c/smoke-result.json` |
| F08 | 空地协同测试区 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/world-batch-r2/sim-73ec96c2d252413b962b8174af316a5f/smoke-result.json` |
| U_ardupilot-gimbal | gimbal | 是 | BLOCKED | BLOCKED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | BLOCKED: asset resources/plugins incomplete; inspect dependency report |
| U_ardupilot-zephyr-parachute | zephyr_parachute | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-a55c381ff28445d9b65bd01f9d34c2f5/smoke-result.json` |
| U_clearpath-construction | construction | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-fdcf457bc29b474b9215c6fed0139a1d/smoke-result.json` |
| U_clearpath-office | office | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-6b4de9f70fa54ae2b8011d5cc4b8c375/smoke-result.json` |
| U_clearpath-orchard | orchard | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-5941b773e36f4c00bb99b20b517c3d63/smoke-result.json` |
| U_clearpath-pipeline | pipeline | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-3d70680111d44c019e557f35f919e10b/smoke-result.json` |
| U_clearpath-solar-farm | solar_farm | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-d9dd10f3645f4e40ae690a9123bfd37a/smoke-result.json` |
| U_clearpath-warehouse | warehouse | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/warehouse-benchmark/sim-9598361aefdf47eeb27818b081770ffe/smoke-result.json` |
| U_collection-f1-maze-s08-perfect-kr | f1_maze_s08_perfect_kr | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-7711498bd7d544a18f90b71baa44426b/smoke-result.json` |
| U_collection-f3-aisles-h30x20-a150-x1 | f3_aisles_h30x20_a150_x1 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-4f9fee44172c43c38228670f32496b22/smoke-result.json` |
| U_collection-f4-forest-s40-d003 | f4_forest_s40_d003 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-e6a8de16fef04502a43ad0523dbbecc5/smoke-result.json` |
| U_collection-f5-urban-w06-b15 | f5_urban_w06_b15 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-504a042d845f4c13b23827576c4bfb6a/smoke-result.json` |
| U_collection-mo1-office-strip-moving | mo1_office_strip_moving | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-77193939bd68494eb5d1fc6e5584baac/smoke-result.json` |
| U_collection-mo2-warehouse-moving | mo2_warehouse_moving | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-e02c70c553ae4012a0afda69140cd000/smoke-result.json` |
| U_collection-sc1-square-loop | sc1_square_loop | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-16bb56f8e6e44cbfa224d97f21ce9a93/smoke-result.json` |
| U_gazebo-air-pressure | air-pressure | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-ede25f70491141769737f787ffb71935/smoke-result.json` |
| U_gazebo-contact-sensor | contact_sensor | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-738987d32cfc4fd4916c233b0e147acf/smoke-result.json` |
| U_gazebo-imu | imu | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-7df9186e44d24247b00ae20eda6a075d/smoke-result.json` |
| U_gazebo-navsat | navsat | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-8da5ab538d0144dbaa5a79ad14d6bf3c/smoke-result.json` |
| U_gazebo-sensors | sensors | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-98623e1d26894b2eb3fcb525e7b0462f/smoke-result.json` |
| U_gazebo-shapes | shapes | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-7b54514d27dd48ef924318756dfb2810/smoke-result.json` |
| U_gazebo-trajectory-follower | trajectory_follower | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-d1ae19557cf64e8785b83fb4e92cd1e3/smoke-result.json` |
| U_gazebo-wind | wind | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-7de2bc4c18074247ba7910f3b94ccae2/smoke-result.json` |
| U_px4-forest | forest | 是 | BLOCKED | BLOCKED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | BLOCKED: asset resources/plugins incomplete; inspect dependency report |
| U_px4-frictionless | frictionless | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-9a7632e5106c406a9f24b1d00f74ce05/smoke-result.json` |
| U_px4-moving-platform | moving_platform | 是 | BLOCKED | BLOCKED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | BLOCKED: asset resources/plugins incomplete; inspect dependency report |
| U_px4-ridge | ridge | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-b7b73a88ccc244ad852b2c2324fdd445/smoke-result.json` |
| U_px4-walls | walls | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-fa845494e8134acfa92260fb68cf6c99/smoke-result.json` |
| H_playpen | Rover 游乐场 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-d408f4afd2894d11b66b587827b9b6c7/smoke-result.json` |
| H_iris | Iris 跑道 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-5ad0c5dce59742b48fb63b31c293e1c4/smoke-result.json` |
| H_zephyr | Zephyr 跑道 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-c10cffc94e0641318666953c57cd50c3/smoke-result.json` |
| H_warehouse | 仓库 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/postfix-worlds/sim-a1c9bf533e764a11b0cb5a02f930ff53/smoke-result.json` |
| H_urban | 城市街区 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-5ffa16a14d3944e48b40bee319778635/smoke-result.json` |
| H_orchard | 果园 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-46f62373776d440281afb0f2072e96b9/smoke-result.json` |
| H_windy | 风场 | 是 | PASS | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | `artifacts/simulation/center-20261029/upstream-batch/sim-fb5ded806f784458814a9380c8dc4766/smoke-result.json` |
| H_multiagent | 多车辆 | 否 | BLOCKED | BLOCKED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | BLOCKED: historical source missing |

各入口的来源、精确版本、许可证、范围、传感器/车型候选、限制见 [场景目录](GAZEBO_SCENE_CATALOG.md) 与机器索引 [center-evidence.json](simulation/center-evidence.json)。逐入口复现：

```bash
vehicle-autonomy-simulation check R01
vehicle-autonomy-simulation smoke --scene R01 --seed 42 --seconds 8 --data-dir artifacts/simulation/recheck-UNIQUE
```

将场景 ID 替换为表内 ID。未安装的依赖维持 BLOCKED；不要以“文件下载完”代替完整依赖检查。源下载状态与本轮测试状态分别记录。历史 H_iris 的旧 SITL FAIL 保留在原 `simulation/world_registry/GAZEBO_WORLD_TEST_MATRIX.md`；本轮 H_iris 仅做无车世界检查。C01 的新配置通过不能反写 H_iris 或 Zephyr 的飞行结论。VTOL 与 F08 协同控制仍未通过，详见 [已知限制](SIMULATION_KNOWN_ISSUES.md)。
