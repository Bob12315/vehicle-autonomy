# Phase 1 第三轮定向修复报告

**状态：READY FOR RE-AUDIT。** 开发侧测试全部通过，等待用户安排独立审查。本文不宣布最终 Phase 1 验收通过；未开始 Phase 2。

## 基线与保留记录

- 起点 `68abd5873d0de6afadc07efb0eb7ff6d76de117f`，工作区干净；分支 `fix/phase1-round3-confirmation`。第二轮独立审查结论 FAIL，唯一阻塞是回绕后旧 ACK/HB 组合错误完成 Disarm。
- 已读两份架构基线、AGENTS、README、架构说明及 Session/CommandPort/TelemetryState/SimulationRuntime/SourceClock 和现有测试。起点全量单元测试为 365 项通过。
- 两份旧报告、两份机器索引、286 份原始日志/结果均核对哈希未变。新证据全部放在 `artifacts/phase1-round3/`；开发失败也保留。
- 用户给出的临时审查目录最初存在，已复制材料并原样执行复现脚本。后续检查时该临时目录已不存在；已保留原 JSONL、脚本及审查元数据于 `review-original/`。脚本在复制目录生成的复现结果保留在 `before-exact-output/`，不冒充审查员原件；详见 `review-original/PROVENANCE.txt`。

## 根因与不可判定性

旧状态机以相邻带 boot 时间的遥测构造窗口，把窗口内的无时间戳 ACK/HB 当成新证据。8 位 packet sequence 回绕后，历史帧可再次落入合法窗口。两份旧心跳也会借用不同的新遥测时间，因此去重数量、接收时间和连续心跳计数都不能证明其生成时间。原 SimulationSourceClock 对 HB 返回接收时间，同样不是源采样证明。
COMMAND_ACK 的 MAV_CMD 400 不区分 Arm/Disarm 请求实例；HEARTBEAT 不携带命令 ID 或可信采样时间。未认证链路中，合法新状态与原样/重打包历史状态可以不可区分，无法同时承诺抗任意重放和无条件完成率。本轮采用保守策略：无可信接收证据不确认 operation/ACK，不进入 COMPLETED；已写出且无充分确认的命令到期为 UNKNOWN。

## 新证据规则与最小修改

| 边界 | 本轮规则 |
| --- | --- |
| Codec / ReceiveSigning | 显式注入 32 字节密钥 epoch 与初始水位；先校验 SHA-256/48 签名，再检查固定的已配置来源（本轮 `(system,component,link)=(1,1,0)`） 和严格增加的 48 位签名时间戳。错误 MAC 不修改水位；一个水位与固定计数字典，不保存无限历史缓存 |
| Session | 未认证或回放的 ACK/HB 不进入规范状态/完成链，也不覆盖更新的可信心跳诊断字段。有效签名心跳直接更新 operation，无需借用相邻遥测时间。签名水位由运行组合持有，在同密钥重连时保留；新飞控/新密钥明确创建新组合 |
| CommandPort | 实际 Writer 发送时保存认证接收水位。ACK 必须有更高的已验证签名时间戳，仍标注 `unproven_mav_cmd_only`；目标 HB 必须独立通过签名校验，且时间戳高于发送水位和 ACK。原两次状态去抖保留，但计数不授予认证资格 |
| SourceClock / Runtime | SourceClock 对 ACK/HB 返回未知采样时间；物理遥测原 boot 映射不变。Runtime 仅增加可选接收校验器和明确的证据字段，不自动配置车辆、不打开实机能力 |
| 测试夹具 | 原正向内存测试显式提供签名证据，所有原断言/安全门槛保留。SITL 仅在 Phase 1 测试显式开启公开接口签名配置，其他 OwnedSimulation 默认不强制开启 |

旧状态机是“序号窗口 + ACK 候选 → ACKNOWLEDGED；两份借用源时间的 HB → COMPLETED”。新状态机是“分别校验认证 ACK 和认证目标状态；无证据不前进；认证有序状态满足原去抖才完成”。正常目标状态持续更新不依赖是否有命令，也不依赖 8 位序号是否回绕。

## 公开协议与真实下行签名验证

- 依据 [官方 MAVLink 2 Signing 规范](https://mavlink.io/en/guide/message_signing.html) 和 [SETUP_SIGNING 定义](https://mavlink.io/en/messages/common.html#SETUP_SIGNING)：签名认证帧来源及签名流的单调时间戳；它不是命令请求 UUID，也不是精确采样时钟。
- 检查本机 pinned ArduPilot 的 `libraries/GCS_MAVLink/GCS_Signing.cpp` 和 MAVLink C helpers：只允许未解锁时设置签名，配置后激活下行签名，时间戳每帧递增；channel 0 允许接收未签名报文。未假定给命令签名就等于验证了下行。本轮只验证下行确认资格，不声称上行已获得签名保护。
- 隔离夹具先从自建 TCP listener 确认未解锁，用公开 SETUP_SIGNING 配置随机 epoch，再发送只读 MAV_CMD_REQUEST_MESSAGE(HEARTBEAT)，实际捕获带签名的 HB 与 ACK 512，并用独立 pymavlink 校验器复核。正式 Arm/Disarm 仍只经过 Execution/Safety/Authority/唯一车辆 Writer。
- 初期存储预置探针没有形成合格下行证据，已保留失败；收到用户指示后取消该实现，不再修改或解析 EEPROM。最终代码只用公开协议接口。未修改外部 AP 源码/二进制/参数或其他旧工程。
- 随机认证密钥不进入日志、报告、Git 或代理 SETUP_SIGNING 报文记录。只使用受保护的临时私有进程配置，结束删除；SITL 自有状态目录权限 0700。证明文件保存实际 HB/ACK 字节、签名时间戳和执行时校验结论，不保存密钥。

## 修复前后与确定性验证

| 项目 | 修复前 | 修复后 |
| --- | --- | --- |
| 原审查原样脚本 | Arm 完成；没有新 Disarm ACK/未解锁 HB；旧帧绕一圈后 Disarm COMPLETED，World armed=false，Writer=2 | 固化原 ACK/HB 字节与原对齐步骤；请求不完成、ACK 不接受、World 仍 armed=true；合法新认证 ACK/状态随后完成，Writer 仍=2 |
| 三次回绕及不可区分的无签名输入 | 序号/接收时间无法提供新鲜度 | 原样签名旧帧与重打包无签名旧状态均无确认资格；正常新状态对照仍完成 |
| 正式 Action/Mission | 可能跟随错误 Effect 完成 | Disarm Action 在回绕重放后保持 RUNNING，命令 TRANSMITTED，World armed=true；新认证确认到来后整个三步 Mission SUCCEEDED，仅 3 次写入 |
| 无可信确认 | 可能被遥测窗口提升 | 实际写入一次；无认证 ACK 不前进；到期 UNKNOWN |
| 长运行 / 重连 | 回绕重新获得资格 | 10,000 周期、1,000 秒模拟时间、70,000 帧、超过 270 次回绕；规范状态持续更新，接收确认内存固定；重连保留水位，新密钥拒绝旧 MAC |
| 原 Writer 期限与授权安全 | 上轮修复基线 | 等锁/Guard 内过期、Lease 到期、异常/超预算/授权变化仍零实际写入；未改原门槛 |

- 全量单元测试：374 项通过，0 失败/错误/跳过。新增 9 项定向用例，原 365 项全部保留。
- 补充长流完成率对照 `long-stream-confirmation.json`：连续 70,000 帧后，再经正式 Execution 发出新的 Disarm，使用新认证 ACK/心跳完成；World 变为未解锁，实际 Writer 仅 1 次。它不替代项目内长运行回归或完整仿真门槛。
- 修复前：`before-exact-replay.log` 与 `before-exact-output/`；旧基线：`baseline-unit.log`；修复后定向/Action/原 Writer 边界日志和正式 unit.json 均已索引。
- 正向夹具增加认证输入，原序号查看用独立解析器，避免“为查看帧而消费真实接收水位”；未删除测试、放宽断言或增加安全/运动/超时阈值。

## 两轮完整真实 SITL/Gazebo A–F

- 固定提交 `89e57ae69f1b69a49c3382b53cb17bc7f3b276ff`，工作区干净；两轮源 SHA256 `338c859df295141e5b31832b34139754e7a4e4bfb9e8aa4069d2ec25170e6ff1`，开始/结束一致。
- ArduPilot `b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`，插件 `3ec51428fd43deb7b71137192ba16394b450d78e`，Gazebo 8.15.0，现有 Rover/Copter 模型/参数。
- 实际入口：`PATH="$PWD/.venv-migration/bin:$PATH" ./scripts/test_phase1_control.sh --remediation --allow-send --run-dir artifacts/phase1-round3/acceptance-final`。两轮各有 Rover/Copter probe、physical、faults，共 12 场景；新回绕场景为强制条件，不替代任何旧场景。

| 门槛 | Rover 1 | Rover 2 | Copter 1 | Copter 2 |
| --- | --- | --- | --- | --- |
| A | PASS | PASS | PASS | PASS |
| B | PASS | PASS | PASS | PASS |
| C | PASS | PASS | PASS | PASS |
| D | PASS | PASS | PASS | PASS |
| E | PASS | PASS | PASS | PASS |
| F | PASS | PASS | PASS | PASS |

| 定向证据 | Rover 1 | Rover 2 | Copter 1 | Copter 2 |
| --- | --- | --- | --- | --- |
| 真实回绕圈数 | 3 | 3 | 3 | 3 |
| 回放后无新 Disarm 证据的结果 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| World 保持 armed | True | True | True | True |
| 被扣留请求实际 Writer 次数 | 1 | 1 | 1 | 1 |
| 新会话合法 Disarm | COMPLETED | COMPLETED | COMPLETED | COMPLETED |
| 正常连续 Arm/Disarm 完成数 | 4 | 4 | 4 | 4 |
| Guard 期间过期 Writer 次数 | 0 | 0 | 0 | 0 |
| 位置目标独立 Gazebo 误差 / m（原 ≤0.75） | 0.490 | 0.486 | 0.112 | 0.112 |

代理实际扣留正式 Writer 的 Disarm 帧，让 AP 保持 armed；新遥测和真实心跳持续推进，观察三次 AP 序号回绕，每圈重放旧 ACK 与两份旧未解锁 HB。逐周期核查命令、World 和写入次数；旧 ACK 无认证资格，请求按原 TTL 到期 UNKNOWN。关闭连接丢弃扣留帧，明确重建会话/重新授权，再用新真实 ACK/状态正常 Disarm。过期扣留帧从未释放给 AP。

- 独立解码核查 198020 条代理原始帧记录，raw_hex/payload/sequence/system/component 一致；实际重放转发 44 次。16 份公开协议签名证明均含实际下行 HB/ACK 及独立校验结论。
- 四个正常连续控制对照均有 4 个 COMPLETED，另外还有回放超时后的新会话恢复。不以一律拒绝确认消息获取通过。

## 使用限制与未认证通道

- 签名证明来源及同一流的严格有序性，不证明 ACK 的唯一请求归属或物理运动因果。COMPLETED 表示本轮规定的目标状态证据成立；运动物理结果仍由原 Gazebo oracle 单独验证。签名时间戳不当作 host TimePoint、命令 UUID 或绝对采样时钟。
- 本轮资格依赖受信的新密钥 epoch / 初始水位和 pinned 签名源。同密钥重连不能清空水位；新进程若无法保留可信水位，须通过受信配置创建新 epoch。不得拿复用密钥、重置的接收水位或来源未知的完整历史流冒充新会话。
- 无密钥/错误签名/重复与乱序签名的 ACK/HB 均不能推进控制结果或覆盖可信 operation；证据不足的已发送请求保持不确定，最终 UNKNOWN。未显式配置接收认证的现有 CLI 组合不能据裸 HB/ACK 宣布完成，可能停留只读或拒绝开始；这是明确的保守功能限制。未为全项目强制配置签名，也未开放实机密钥管理/控制。
- 不声称抵抗私钥泄露、可签名恶意飞控、伪造可信初始水位、任意未知历史流或精确物理采样时间攻击。本轮没有对这些部署条件签发安全资格。
- 正常 signed HB 在每次有效接收时继续更新，不因没有待执行命令而停用。未认证原始数据可供诊断，但不会借助相邻遥测提升为可信操作状态。
- 双 SEND 默认关闭、hardware_controlled 拒绝、Authority/Lease/Session/Generation/TTL/Safety 和唯一车辆 Writer 保持原链。没有连接真实飞控或实车；串口单元测试仅为临时伪终端。

## 证据、开发失败与清理

- 正式 suite 开始 `2026-10-23T10:02:12.225777+00:00`，结束 `2026-10-23T10:29:42.113619+00:00`；独立轮次 `run-1-5092620d`, `run-2-d11fdc4d`。
- [机器证据索引](v1.1/phase1-round3-evidence.json) 记录所有正式文件哈希、阶段退出状态、真实下行签名证明、重放/UNKNOWN/正常对照、历史保护与资源核查。
- 开发中失败全部保留：初始签名能力探针、早期接收顺序问题，以及两类车故障夹具在新 AP 密钥 epoch 上沿用旧校验器导致的 fresh-state 超时。最后一项通过显式替换组合修复，未清空同密钥防重放水位；最终完整两轮包含该修复。
- 最终 12 个场景、36 个仿真子进程、14 个阶段进程均已结束；包含开发探针的全部 24 份 manifest 另作 PID/进程组、TCP/JSON UDP/RC UDP 与私有配置清理检查，无残留。
- 原始大日志留在独立 artifacts 目录，不纳入 Git；不把开发失败改写为 PASS。源/参数/安全阈值保护记录见索引。

## Git 提交与交付状态

- `6151f65`：接收认证、独立状态证据与定向测试/真实代理/公开签名支持。
- `1e13279`：SITL 新密钥 epoch 显式组合替换。
- `89e57ae`：原审查 ACK/HB 字节的永久回归；完整两轮固定在此版本。
- 报告提交 SHA 使用 `git log -1 --format=%H -- docs/PHASE1_REMEDIATION_ROUND3_REPORT.md` 获取，最终答复给出最终提交和工作区检查结果。

**READY FOR RE-AUDIT：开发侧测试全部通过，等待独立审查。修复完成后停止，不开展 Phase 2。**
