# 受信本机 ROS 2 权限边界：资格验证

Domain 和 namespace 仅用于隔离命名，不能当作身份认证。Phase 5 私有 ROS 前缀新增官方
SROS2 0.13.6，APT 签名元数据及包 SHA-256 已核验；扩展没有覆盖前缀中已有文件，也没有修改
系统或旧 ROS 前缀。`sros2-extension/manifest.json` 记录原清单摘要和新增文件。

`app.bootstrap.ros2_security` 调用官方 keystore/create_enclave/create_permission API，
不读取密钥内容。显式 XML 权限按角色区分 topic、service 和 action；未知字段拒绝。
只读角色可订阅数据、发布普通 ROS 日志及提供类型描述，默认没有 Goal 调用或速度发布权。
使用 Fast DDS 的原生认证、加密和权限，策略为 Enforce。生产导航各角色仍需联合装配验证。

真实协议对照 `dev-dds-security-2/summary.json`：授权端收到 32 条数据并完成一个 Goal；
只读端收到 27 条，创建速度 Publisher 和调用 Goal 被拒；未认证端在合法生产端持续存活时
收到 0 条。服务器实际执行 Goal 数为 1，不能只凭配置或进程启动认定权限有效。
该 probe 不启动 SITL 或车辆控制，不代替完整 Nav2/SITL 授权验收。

所有测试 CA 和 enclave 私钥先登记到新建的自有私密状态目录，再生成；退出沿用已验收的
OwnedCredentials 销毁内容并删除目录，记录 credentials_removed、进程组和端口清理。
凭据内容不进入日志或 Git。此机制不保护同 UID 的恶意管理员窃取密钥，也不声称实现跨任意
主机的全局资源协调；Phase 3 固定根 ProviderRegistry/Ledger 和车辆双 SEND/Lease/Safety
仍是必须的独立边界。

依据为实际安装的官方 SROS2 0.13.6 包内 API、policy schema、DDS governance 和 permissions
模板，包版本/哈希及真实收发记录均已归档。第一轮因缺少 Jazzy 类型描述服务的明确权限而失败，
记录保留；没有开启通配 Goal/运动权限来绕过失败。
