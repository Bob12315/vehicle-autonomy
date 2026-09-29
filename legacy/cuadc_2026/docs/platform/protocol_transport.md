# Vehicle / Protocol / Transport

**状态：Frozen Target Architecture。** 三层各自独立，不能把 MAVLink 与某种连接方式绑定。

| 层 | 回答的问题 | 职责 |
| --- | --- | --- |
| Vehicle Adapter | 这句话对这辆车意味着什么？ | 车辆状态映射、能力、命令语义和翻译 |
| Protocol | 怎么表达这句话？ | 编码、解码和协议消息含义，如 MAVLink、CAN protocol、自定义二进制协议 |
| Transport | 怎么把字节送过去？ | open、close、send/receive bytes、connection status、reconnect |

```text
Vehicle semantics → Protocol → Transport → Physical communication

ArduPilot Multirotor → MAVLink → USB Serial
ArduPilot Multirotor → MAVLink → UDP Ethernet
```

同一 MAVLink Protocol 实现应可复用 SerialTransport 或 UDPTransport，不能每种 Transport 重写一套 MAVLink。Transport 可以是 Serial、UDP、TCP、CAN transport 或 network stream；它只处理字节与连接，不理解 GPS、ARM、takeoff、ATTITUDE 或 vehicle position。Protocol 不包含 Mission、AI 或应用决策。Vehicle 上层逻辑不应因 USB 改成 UDP 而改变。当前 `telemetry_link/` 仍混合部分职责，属[迁移现状](../migration/current_state.md)，不能据此改写目标边界。
