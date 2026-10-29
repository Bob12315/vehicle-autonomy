# Mission Studio 动作分类与本地化交付

2026-10-29。范围是 Mission Studio 的展示目录、左侧动作库和参数显示。
没有修改 Registry 身份、ActionSpec、执行契约、Mission JSON 格式、控制权、安全策略或 Tool Agent。

## 审计结果

[自动生成的完整目录](MISSION_ACTION_CATALOG_ZH_CN.md)包含每项中英文名称、中文用途、参数说明、原始输入输出 Schema、实现模块、车型和依赖限制。

真实注册代码的并集共有 **42 个明确身份**，各有且只有一个主分类：

| 分类 ID | 分类 | 数量 |
| --- | --- | ---: |
| vehicle | 车辆基础控制 | 13 |
| navigation | 运动与导航 | 12 |
| safety | 安全与状态 | 7 |
| perception | 感知与识别 | 3 |
| actuation | 设备与执行器 | 1 |
| data | 数据与计算 | 1 |
| integration | 外部能力 | 1 |
| composite | 复合任务能力 | 4 |

逻辑编排和子任务单独显示，不计入这 42 个 Action。没有将 Gazebo、QGroundControl 或 RViz2 归入 Action。
这 42 项跨多个显式装配入口，不代表一次启动全部注册。页面以实际 Registry 为准。
动态外部作业的 ID 由部署指定，没有固定全局清单；实际注册时按 managed 契约归入外部能力。

仅软件演示的感知和执行记录始终标注为软件记录，不声称真实视觉检测、舵机或物理载荷能力。
早期 basic / 场景动作使用原有 opaque 生命周期；Studio 不因它们存在于源码就假定已验证 Provider。

## 用户可见行为

- 八个可折叠主分类，以及独立的逻辑、子任务、收藏和最近使用区域。
- 名称、简介、标签、参数说明、支持车型、Provider 描述和不可用原因默认中文。
- 同时支持中文名称、原始英文 ID、英文名称和参数帮助搜索。
- 默认按任务的实际目标车型筛选；可切换显示全部或某车型。不同车型及未绑定 Provider 的条目禁用，并说明原因。
- “可配置”只表示可以加入任务图，执行时仍检查真实状态、控制权、发送授权与安全策略。
- 收藏和最近使用按原始 ID 与版本保存；分类、筛选、收藏操作不会启动 Action。
- 节点默认中文，保留用户自定义显示名；属性面板可展开原始 Action ID 和版本。
- 参数显示中文名称、帮助、单位、范围、默认值、必填状态和原始字段；没有声明范围时如实说明。
- 纳秒参数显示秒，以整数纳秒保存，避免浮点乘法尾数和不精确的整数写回；其他坐标、角度、速度不改变数值含义。
- 数组和固定元组遵循原始 Schema；复杂参数仍保留原始字段及 JSON 编辑能力。
- Runner 和逻辑端口中文显示，原始状态、日志与诊断保留；未知错误回显原始内容。
- 原有发布、执行、共享变量绑定、子任务、恢复登录及权限检查继续使用同一链路。

## 前后端模块

| 模块 | 职责 |
| --- | --- |
| `app/mission_designer/action_localization.py` | 独立的双语动作展示目录、参数说明、审计范围及分类 |
| `app/mission_designer/action_catalog_report.py` | 调用真实注册函数生成源码清单，不启动动作或连接设备 |
| `app/mission_designer/studio_service.py` | 在原字段之外附加 presentation、library_sets、分类及设计时可配置性 |
| `app/web/mission_control.py` | 提供一个新增的动作库静态脚本 |
| `app/web/static/studio-library.js` | 分类、筛选、搜索、收藏、最近使用、基础语言切换与展示 Schema |
| `studio-b.html/js/css` | 接入现有布局与动作库；展示原始 ID、参数说明与运行状态 |
| `studio-canvas.js` | 中文节点、逻辑端口与带正确单位的参数摘要；保留原始身份 |
| `studio-params.js` | 递归参数帮助、验证、固定元组编辑与精确纳秒转换 |
| `auth.js` | 未知错误保留原文，缺失词条安全回退；认证、会话及请求权限逻辑不变 |

原 API 的 name、version、parameters、output、vehicle_types 等字段均保留，未将中文写进执行字段。
新增展示元数据不会进入保存或导出的 Mission。Blackboard 用户变量名、数据值和引用路径不参与翻译。

## 国际化与新增动作

默认 `zh-CN`，提供动作库及相关展示的基础 `en-US` 切换。其他已有页面仍以中文为主，不声称已完成全站英文版。
动作名称、描述、参数标签和帮助由独立 Localization Catalog 提供，不依赖批量修改程序 ID。
通用界面词条集中在 StudioLocale，复用现有 VAFI18n 的中文基础词表。

新增动作先按原方式注册，再选择以下方式之一补充展示信息：

1. 在 `ACTION_TEXT` 添加主分类、中英文名称和经实现核对的中文说明；参数写入 `PARAMETERS`。
2. 在受信任的 factory 上声明 `ui_metadata`，包含 category、display_name、description、parameters、tags、dependencies。

示例（仅展示元数据，不注册新执行能力）：

```python
factory.ui_metadata = {
    'category': 'data',
    'display_name': {'zh-CN': '数据校验', 'en-US': 'Validate data'},
    'description': {'zh-CN': '按已有契约校验输入数据', 'en-US': 'Validate inputs using the existing contract'},
}
```

未分类动作进入“未分类”并给出原因；缺少中文时回退英文或原始 ID，仍可查看和编辑原契约。
展示元数据不能修改所需能力、车辆类型、执行 Schema 或 Provider 绑定。

重新生成目录：

```bash
.venv/bin/python -m vehicle_autonomy.app.mission_designer.action_catalog_report \
  --output docs/MISSION_ACTION_CATALOG_ZH_CN.md
```

## 测试与实际边界

- 完整项目单元测试：**818 项通过**，包含原有 813 项及 5 项新增目录/兼容性测试。
- 新增真实 Chrome + 隔离 HTTP 验证：八类动作、独立逻辑与子任务、车型和 Provider 筛选、禁用状态、收藏与最近使用、中文/ID/参数帮助搜索、中文数值校验、基础英文切换、原始字段/引用路径、导出与重新加载均通过。
- 纳秒往返：显示 `4.000000001` 秒，保存 `4000000001` 整数纳秒；默认 15 秒无浮点尾数，刷新后恢复一致。
- 原 Mission Studio 浏览器回归：创建、图编辑、类型参数、保存发布、断点单步、真实软件执行器、共享变量及软件子任务示例通过。
- 全页面中文浏览器回归通过；统一认证回归验证跨页、刷新恢复、过期、退出、断线和三车型页面。
- JavaScript 语法检查与 Git 空白检查通过。

浏览器证据位于 `artifacts/mission-studio-b/action-library-release/`、
`artifacts/mission-studio-b/classified-release/` 与 `artifacts/web-zh/`，不加入 Git。
测试使用明确的隔离车辆状态和软件执行器，没有连接真实车辆、没有运行真实 SITL 飞行，也没有重新验收硬件导航或物理执行器。

## 保留原文的内容

用户定义的任务名称、节点名称、变量名、引用路径、输入值、原始日志、错误码、程序 ID、完整 Schema / JSON 和协议缩写保留原文。
动态外部动作没有部署提供的中文元数据时，名称和参数帮助回退英文或原始标识，不编造能力、翻译或就绪状态。

更新后需重启 Web 后端以载入新增目录接口和静态脚本路由，再进入 `/studio`。
页面左侧为“任务编排”；打开任务后查看分类动作库。服务的启动与车辆仿真授权方式沿用原说明。
