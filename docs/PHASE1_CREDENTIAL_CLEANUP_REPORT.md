# Phase 1：临时 SITL 签名凭据清理修复

**状态：READY FOR RE-AUDIT（仅本次 P2 修复，等待独立复核）。**

本次仅处理条件验收后的 P2 凭据残留。基线为
`3d96e5cff69b52ff44477677cdd2758f17c5156c`，分支为
`fix/phase1-test-credential-cleanup`。不重新宣布 Phase 1 最终通过，不进入 Phase 2。

## 根因与修复

原 `OwnedSimulation.close()` 只 unlink 接收端的
`receive-signing*.private`，没有处理 ArduPilot 通过公开 `SETUP_SIGNING`
接口持久化到 `sitl_state*/eeprom.bin` 的临时密钥。目录权限 0700
限制了访问，但不能代替凭据销毁。

修改限于测试设施、测试、忽略规则及本次报告/证据清单；`src/` 全部保持基线字节，
包括控制状态机、Execution、Authority、Safety、签名接收策略与唯一 Writer。

- `tests/simulation/credentials.py`：只登记本轮新建的私有状态目录及独占创建的
  私有配置；持久化 device/inode 身份，拒绝接管已有目录、路径越界、根目录软链接、
  身份替换和多硬链接文件。目录内软链接只移除链接，不访问外部目标。
- `tests/simulation/launch.py`：登记后、写入凭据前保存所有权信息；退出时先停止
  所有自有进程，再预检资源，覆盖文件内容、fsync、截断、fsync、unlink 并删除自有状态目录。
  包含重启时的多个状态目录。不再通配删除同名但未登记的用户配置。
- `tests/simulation/harness.py`：场景被强制终止后，父程序按 PID/start_ticks
  核实并终止自有进程，确认进程组退出，再依据持久化登记兜底销毁。没有登记的历史
  manifest 不会被自动接管。有存活写入者、身份异常或销毁失败时明确失败，不能假报清理成功。
- 新增定向清理测试及可重复的真实双车型验收入口；忽略临时私有配置和本次运行产物。

清理不解析或修补 EEPROM 存储格式，不修改任何外部 ArduPilot 项目。
正常签名通信仍通过公开协议实际收发、接收端认证及独立 pymavlink 校验验证。

## 修复前后与自动化测试

独立原始证据位于 `artifacts/phase1-credential-cleanup/`，不覆盖以前的验收目录。

| 检查 | 结果与证据 |
| --- | --- |
| 基线全量单元 | 374/374，`baseline-unit.log` |
| 修复前同一清理回归 | 稳定 FAIL：启动异常后调用 close，EEPROM 仍存在；`before-cleanup.log` |
| 修复后清理及 harness 定向测试 | 20/20，含 12 项新增清理测试；`targeted.log` |
| 修复后全量单元 | 386/386，0 失败、0 错误、0 跳过；`unit.json`、`unit.log` |
| 场景 SIGKILL、独立 Writer 子进程仍在运行 | 父程序停止 Writer 后销毁状态；场景保持失败结果，清理成功；`forced-exit/summary.json` |
| 开发态 Rover/Copter 真实 Gazebo + SITL | 两车均通过正常签名/控制和退出清理；`real-regression/summary.json` |
| 已提交版本 Rover/Copter 真实 Gazebo + SITL | 两车均通过；`real-final/summary.json` |

新增测试覆盖启动失败、正常退出、重复 close、重启多状态目录、私有配置、已打开的
旧文件描述符、异常停止、仍存活 Writer、父进程兜底、已有用户目录、同名未登记配置、
软链接目标保护、硬链接拒绝及身份替换。覆盖/截断后，原先已打开的文件描述符也读不到旧内容。
保留所有旧测试，不修改运动、安全、期限或物理误差阈值。

真实验收命令：

```bash
.venv-migration/bin/python -m tests.simulation.credential_acceptance \
  --allow-send --run-dir artifacts/phase1-credential-cleanup/real-final
```

该入口复用既有 `phase1_probe --review-remediation`，两车都必须实际收到经过认证的
ACK/HEARTBEAT、连续 Arm → Disarm → Arm → Disarm 完成，实际 Writer 有写入。
同时复测旧 ACK/HEARTBEAT、三次序号回绕、UNKNOWN 降级、锁等待及 Guard 期间过期、
拒绝后新命令正常发送和重连。不是以拒绝全部确认消息取得结果。

最终结果（两车使用同一已提交代码、同一源码哈希）：

| 车型 | 正常连续 Arm/Disarm | 旧报文三次回绕重放 | 实际 Writer 调用 | 退出清理 |
| --- | --- | --- | --- | --- |
| Rover | 4/4 COMPLETED | UNKNOWN，旧 ACK 未接受 | 10 | 状态/私有配置无残留，端口释放，进程组为空 |
| Copter | 4/4 COMPLETED | UNKNOWN，旧 ACK 未接受 | 10 | 状态/私有配置无残留，端口释放，进程组为空 |

真实回归代码提交为 `c3ab260ac242270e438b4937931799de5a8d3c00`；
源码哈希为 `e56a0ca0c6c1ce5f46aa7d0af7c064c393ef4f0ea099fa26fb4dd8410c94b8dd`。
机器可读结果及本次 65 个非敏感原始产物的 SHA256 见
[本次证据索引](v1.1/phase1-credential-cleanup-evidence.json)。最终核查本次 9 个进程身份均已退出，
自有仿真端口可重新绑定，新运行的状态目录及项目测试私有配置残留均为 0。
源代码提交后的未提交内容仅为本次报告、历史销毁清单、结果索引和 README 说明，未混入控制代码变更。

本次没有重新执行完整物理运动 C 组及全部 A–F；这是按本任务 P2 范围进行的定向回归，
不能冒充一次新的完整 Phase 1 验收。

## 历史凭据与二进制证据处置

完整逐文件销毁与保留清单见
[`docs/v1.1/phase1-credential-destruction.json`](v1.1/phase1-credential-destruction.json)。

1. 扫描项目历史测试产物中的 508 个 EEPROM，仅检查签名存储标记，不解码密钥。
   28 个带标记的载体全部位于已结束的第三轮自有测试目录。
2. 按历史 manifest 的来源、车型、SITL 启动命令、结束记录、PID/start_ticks 和
   状态目录对应关系确认所有权。对这 24 次测试的 30 个 EEPROM 实施覆盖、截断及删除；
   包括正式两轮验收的 16 个、开发/能力验证的 14 个。额外两个无标记载体也属于同一明确
   自有测试范围，一并销毁。没有删除其他位置的旧项目或其他 478 个 EEPROM。
3. 历史清理只删除 EEPROM，保留原目录中的 DataFlash 日志、terrain、原始代理记录、
   签名报文、summary 和 manifest。该系列 373 个非敏感证据文件与 6 个原报告/索引逐一
   校验未变。三份原证据索引的 445 个文件哈希仍一致；原 PASS/FAIL 结论未修改。
   另登记独立审查临时目录中原文件的哈希，未修改其内容。
4. **上述 30 个原始 EEPROM 二进制现已不可用。** 清单保留删除前路径、大小与
   SHA256，状态为 `destroyed_unavailable`，删除后哈希为 null；不声称删除后仍与原哈希一致。
   这些 EEPROM 原本未列入三份索引的 `files` 数组，因此“索引文件哈希仍一致”不表示
   所有历史二进制都还存在。原始签名帧虽仍保留，旧密钥销毁后也不能再用旧密钥
   重新计算其 MAC；保留的是当时在线/独立验签结果，可用新的隔离运行重新验证。
   此次销毁事实是对历史清理不完整记录的独立补充。
5. 历史清理后，保留的 478 个 EEPROM 均无所检查的签名存储标记，历史私有配置残留为 0。
   新回归运行使用独立目录，不与历史清理混用。日志、报告、Git 均不记录认证密钥或
   SETUP_SIGNING 的密钥载荷；销毁清单只记录文件元数据和单向哈希。

## 边界与提交

此修复销毁测试目录中可由文件/API 恢复的凭据内容，也覆盖已打开文件描述符看到的内容。
不把普通文件覆盖虚称为对 SSD 磨损均衡、文件系统快照、外部备份或物理取证的绝对安全擦除；
也不保证 Python 不可变 bytes 在 RAM 中原地清零。退出时释放本进程密钥引用；运行中的
认证状态不作改变。整机断电或连同兜底父程序一起被 SIGKILL 无法执行清理，本报告不声称
这类情况下执行过销毁；异常运行必须按登记资源完成清理后才能视为合格。

代码提交：`c3ab260ac242270e438b4937931799de5a8d3c00`。
报告及销毁清单在后续独立提交中归档；具体报告提交可用
`git log -1 --format=%H -- docs/PHASE1_CREDENTIAL_CLEANUP_REPORT.md` 查询。
最终检查范围包括工作区状态、源代码不变、历史证据保留、仿真进程/端口释放及凭据残留。
