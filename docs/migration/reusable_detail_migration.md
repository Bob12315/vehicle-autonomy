# 原程序可复用实现迁移

**状态：分组实施，生产 owner 尚未切换。** 本轮先将 CUADC Action 实现和定义表迁入 `applications/cuadc_2026/actions/`。生产组合与离线 Mission 模板校验从新位置读取；原 `missions/common/actions/` 路径保留薄兼容导入，供仍使用旧模块路径的测试和外部调用者过渡。Action 的参数、默认值、Effect 和 Mission JSON 均未改变。

后续每组遵循同一门禁：新 owner 持有唯一实现，生产调用方使用新路径，离线回归核对行为，旧路径无代码/测试/工具调用方后再删除。不能因文件已搬迁就认定旧 Runtime 可删。生产 Mission/Action owner、飞控和服务器验证仍另行处理。
