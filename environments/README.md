# 本机软件与环境索引

主程序位于 `src/vehicle_autonomy/`。Gazebo、ArduPilot、QGroundControl、RViz2、
ROS 2 和第三方大型模型使用仓库外的本机安装，不复制进源码或测试产物目录。

复制 `tools.example.toml` 为 `tools.local.toml`，按需填写绝对路径。模板受版本管理，
本机索引忽略版本管理、不进入 wheel。配置也可放在
`$XDG_CONFIG_HOME/vehicle-autonomy/tools.toml`（默认 `~/.config/vehicle-autonomy/tools.toml`），
或用 `VAF_ENVIRONMENT_CONFIG` 指定。文件选择顺序为显式配置、仓库本机索引、用户索引；
只选一个文件，不合并过时路径。路径优先级为显式调用参数、现有 `VAF_*` 环境覆盖、
本机索引、受控默认发现。显式路径缺失时不会切换另一套软件。

`paths` 管理软件目录、ROS 初始化脚本/工作空间及外部资源目录；`executables` 管理
实际程序路径；`environment` 是受信任子进程环境；`versions` 记录版本标签；
`checksums` 记录关键文件 SHA256。凭据只使用私密文件引用，不写入此文件。

`vehicle-autonomy-environment check` 输出路径、安装检查和校验结果，不启动软件。
缺少可选软件不表示主程序不能运行；相关功能必须单独检查就绪状态。
普通 Rover 的官方外部模型使用 `paths.sitl_models_root`，或环境覆盖
`VAF_SITL_MODELS_ROOT`；目录应包含 `Gazebo/models/wildthumper`。版本和文件锁见
`simulation/vehicles/catalog.json`，准备方式见 [WildThumper](../docs/WILDTHUMPER_ROVER.md)。
`scripts/with_ros2.sh COMMAND...` 使用同一索引，ROS 仅进入显式工作进程。

`runtime/state` 是持久状态，`runtime/sessions` 是有归属的运行会话，
`runtime/logs` 是日常日志，`runtime/cache` 是可重建缓存。源码安装默认使用工作区
`runtime/`，wheel 默认使用用户 state 目录；可用 `VAF_RUNTIME_ROOT` 显式指定。
`artifacts/` 只存测试与导出结果，正常启动不从中读取软件。
