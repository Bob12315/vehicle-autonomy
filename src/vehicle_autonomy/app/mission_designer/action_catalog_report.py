"""Generate an audit from real registration functions without starting any Action.

This union is a source inventory, not a running deployment or hardware claim.
Native factory initialization is deliberately bypassed: no ROS/resource binding,
vehicle connection, external process or worker is opened by documentation.
"""
import argparse
import json
from pathlib import Path

from .action_localization import CATEGORIES,PARAMETERS,catalog_entry


def audit_registry():
    from vehicle_autonomy.engine.action.registry import ActionRegistry
    from vehicle_autonomy.actions.catalog import register_standard
    from vehicle_autonomy.actions.common.basic import register_basic
    from vehicle_autonomy.actions.composite.cuadc import register_targets
    from vehicle_autonomy.actions.simulation.studio_demo import register_demo
    from vehicle_autonomy.actions.common.sitl_mode import SITL_MODE_SPEC,SITL_ARM_SPEC,SITL_DISARM_SPEC,SitlModeAction,SitlArmAction,SitlDisarmAction
    from vehicle_autonomy.actions.rover.maneuver import SPEC as MANEUVER,ManeuverAction
    from vehicle_autonomy.actions.navigation.path_following import SPEC as FOLLOW,FollowPathAction
    from vehicle_autonomy.actions.navigation.native_rover import register_native_navigation,NativeRoverNavigationFactory
    registry=ActionRegistry()
    for register in (register_standard,register_basic,register_targets,register_demo):register(registry)
    for spec,factory in ((SITL_MODE_SPEC,SitlModeAction()),(SITL_ARM_SPEC,SitlArmAction()),(SITL_DISARM_SPEC,SitlDisarmAction()),(MANEUVER,ManeuverAction()),(FOLLOW,FollowPathAction(None))):registry.register_typed(spec,factory)
    register_native_navigation(registry,object.__new__(NativeRoverNavigationFactory))
    return registry


def generate():
    registry=audit_registry()
    items=[catalog_entry(registry,item) for item in registry.catalog()]
    lines=['# Mission Studio 动作分类与中文目录','',
        '由真实注册函数和独立展示目录自动生成：',
        '`python -m vehicle_autonomy.app.mission_designer.action_catalog_report --output docs/MISSION_ACTION_CATALOG_ZH_CN.md`','',
        f'源代码中有 {len(items)} 个明确身份的类型化动作。此表是多个显式装配入口的并集，不是当前后端已经注册或可执行的清单。',
        '审计只提取契约，不启动动作、ROS、外部进程或车辆连接。历史单一安装包布局与安全边界保持不变。',
        '具体页面只展示当前 Registry 中的真实条目；能否配置由实际车型、能力和 Provider 绑定计算，执行仍重新校验控制权、双发送门与安全策略。',
        '没有独立注册的舵机、相机触发或真实视觉检测动作，不能因分类存在就声称具备该能力。软件演示明确标注为软件记录。',
        '外部作业通过 `register_external(registry, name, ...)` 接受部署给定的 ID，没有固定全局名称；这类实际注册会自动归入外部能力，未翻译字段保留原文。','',
        '## 注册与装配边界','',
        '- 独立车辆控制：`actions.catalog.register_standard`，三车型仿真能力；不赋予实机控制资格。',
        '- 基础/场景/目标动作：Application 的显式仿真环境装配；原始生命周期为 opaque，不能在 Studio 中假定已绑定。',
        '- `navigation.follow_path`：需要已验证的路径源、坐标变换绑定和车辆模型。',
        '- `NavigateToPose`：需要已明确启动和绑定的原生 Nav2、地图、定位及外部资源；未绑定时不可配置。',
        '- `sitl.*`：专用诊断或 Application 装配，不是默认控制入口。',
        '- `Sim.*`：只有显式软件演示注册，不进行真实检测、飞行或载荷动作。','',
        '## 分类及中英文名称','',
        '| 原始 Action ID | 中文名称 | 英文名称 | 主分类 | 支持车型（展示审计） |',
        '| --- | --- | --- | --- | --- |']
    for item in items:
        p=item['presentation'];lines.append(f"| `{item['name']}` | {p['display_name']['zh-CN']} | {p['display_name']['en-US']} | {CATEGORIES[p['category']]['label']['zh-CN']} | {', '.join(p['vehicles']) or '由具体契约决定'} |")
    lines+=['','## 参数中文对照','',
        '表中单位均为原始契约单位；纳秒字段在编辑器显示秒并精确换回整数纳秒。其他字段保留原单位和数值。',
        '数值范围、默认值与必填标记来自真实 Schema，并补充已审计的构造器约束；跨字段及条件约束仍由原动作验证。','',
        '| 原始字段 | 中文名称 | 原始单位 | 中文说明 |','| --- | --- | --- | --- |']
    for key,value in sorted(PARAMETERS.items()):lines.append(f"| `{key}` | {value['label']['zh-CN']} | {value['unit'] or '—'} | {value['description']['zh-CN']} |")
    lines+=['','## 逐项契约、来源与输出','']
    for item in items:
        p=item['presentation'];lines += [f"### `{item['name']}@{item['version']}` — {p['display_name']['zh-CN']}",'',
            p['description']['zh-CN'],'',
            f"- 实现：`{item['implementation']}`；参数类型：`{registry.resolve_typed(item['name'],item['version']).spec.parameters_type.__module__}`。",
            f"- 主分类：`{p['category']}`；支持车型：{', '.join(p['vehicles'])}。原始 Registry 车型字段：`{item['vehicle_types']}`（空列表不代表已验证全部车型）。",
            f"- 生命周期：`{item['external_lifecycle']}`；所需能力：`{item['required_capabilities']}`。",
            '- 依赖及限制：'+p['dependencies']['zh-CN'],
            '- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。',
            '- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：','', '```json',json.dumps(item['parameters'],ensure_ascii=False,indent=2),'```','',
            '- 输出结果原始 Schema：','', '```json',json.dumps(item['output'],ensure_ascii=False,indent=2),'```','',
            '未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。' if item['output'] is None else '输出字段与原契约完全一致，用户变量及引用路径不重命名。','']
    lines+=['## 扩展方式','',
        '新增动作仍先通过 Registry 注册。分类和翻译可加入 `action_localization.ACTION_TEXT` / `PARAMETERS`，或在受信任的 factory 上提供 `ui_metadata`（category、display_name、description、parameters、tags、dependencies）。',
        '显示名称和说明使用 `zh-CN` / `en-US` 字典。未提供翻译时回退英文或原始 ID；未提供分类时进入“未分类”并说明原因。不得通过此元数据更改能力、Schema、车辆权限或 Provider 就绪状态。',
        '前端收藏和最近使用仅保存动作 ID 与版本；不保存密钥或任务参数。仅动作库和相关展示提供基础英文切换，其他已有页面仍以中文为主。',
        '底层错误没有准确中文对应时显示原始错误，不生成猜测解释。原始 ID、原始日志和完整诊断始终保留。','']
    return '\n'.join(lines)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.write_text(generate())
