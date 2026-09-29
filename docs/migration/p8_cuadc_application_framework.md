# P8 CUADC Application 框架边界

**状态：CUADC 2026 应用组合入口已落地；比赛算法和配置值仍在原实现。** 本轮按“只修改框架，具体细节之后完善”实施，不调整 Mission 步骤、投放排序、伺服输出、场地几何、YOLO 参数或控制逻辑。

`applications/profile.py` 定义通用 `ApplicationProfile`、Mission 模板引用与目录。`applications/cuadc_2026/` 是当前应用组合的 owner，声明并使用以下现有部件：

| 组成 | 当前绑定 |
| --- | --- |
| Deployment | `onboard_rk3588` Profile |
| Vehicle | `multirotor` |
| Protocol / Transport | `mavlink` / UDP 或 Serial，由现有 telemetry 配置选择 |
| Sensor / Perception | USB camera / `yolo_rknn`，仍走当前 RK3588 RKNN 实现 |
| Environment | `cuadc_2026`，现有 Field 校准和坐标变换保留 |
| Application | `cuadc_2026` |
| Mission | `rescue_2026_full_auto`，以及 `drop_two_targets`、`recon_gps` 分项模板 |

CUADC Action 集合和车辆能力预检从 `application/vehicle_composition.py` 移到 `applications/cuadc_2026/composition.py`，原路径保留兼容导出。生产 SystemRunner 明确绑定当前应用 Profile，并从中读取 Environment ID；Web 模板目录与校验脚本使用同一 Mission 模板清单，原 URL、返回路径与 JSON 文件位置不变。候选 Core 的 EnvironmentSnapshot 现在通过注入 Port 取得，不再导入 CUADC 适配器；FieldReference 旧快照仍作为兼容输入。

## 仍在原路径的应用细节

- `config/action_missions/*.json`、`config/field_profiles/competition_runtime.json` 和 `config/yolo.yaml` 保持生效路径；Profile 只是明确记录这些资产的归属，不复制配置。
- `missions/common/actions/` 内的目标选择、GPS 侦察、payload release 等 Action 实现和 `action_lab.py` 中的比赛默认参数尚未迁入应用包；当前注册由 CUADC composition 选择。后续搬迁须保留 Action Contract、白名单和旧导入兼容。
- `field/` 仍拥有实用校准、变换和比赛几何；P6 的 Environment adapter 仍是只读边界。
- 通用 `missions/core/`、`contracts/core/`、`application/core/` 已无 CUADC、bucket、drop_zone、recon_area 或 rescue_2026 硬编码；生产 `application/` 仍有旧 Field/Web 投影，待逐项迁移。

## 回归范围

P8 测试验证应用组合引用已存在的 Deployment / Environment、Action 注册与模板、Web 与离线校验共享清单，以及 Core 不含 CUADC 字符串。Mission loading、Action registry、Web、telemetry、perception、Field / Environment 和 Safety 的离线测试由全量套件覆盖。全量结果为 762 passed、3 failed；3 项失败均在 P8 前已存在，分别涉及 strict profile 行数限制、align_descend 行数限制和 goto settle time。正式三个 Mission 模板离线校验、架构边界及稳定核心校验通过。`executor.send_commands: false` 默认值和现有 SEND / Action 双门控未改。真实 SITL、飞控、相机与 RK3588 NPU 本轮未连接，不能把离线回归视为实机验收。
