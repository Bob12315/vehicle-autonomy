"""Navigation describes installed UI capabilities, never control authority."""


def navigation(application):
    local = getattr(application, 'control_center', None) is not None
    tools = getattr(application, 'tool_service', None)
    remote = bool(tools and getattr(tools, 'remote_enabled', False))
    if tools is not None:
        with tools.registry.lock:
            remote = remote or bool(tools.registry.agents)
    items = [
        ('dashboard', '/console#dashboard', '车辆总览', '遥测与运行状态'),
        ('simulation', '/simulation', '仿真中心', '场景、车辆与出生点'),
        ('control', '/control', '车辆控制', '手动操作与控制权'),
        ('studio', '/studio', '任务编排', '任务编辑与运行'),
    ]
    if local:
        items.append(('center', '/center', '工具与系统', '桌面工具、日志与进程'))
    advanced = [('actions', '/', '动作实验室', '单个 Action 调试')]
    if remote:
        advanced.extend([
            ('tools', '/console#tools', '远程工具', '已配置的代理主机'),
            ('workspaces', '/console#workspaces', '远程工作区', '工具依赖与运行环境'),
            ('logs', '/console#logs', '远程日志', '代理工具输出与审计'),
            ('settings', '/console#settings', '远程设置', '车辆上下文与运行配置'),
        ])
    def entries(values):
        return [dict(id=key, href=href, label=label, description=description)
                for key, href, label, description in values]
    return dict(local=local, remote=remote, items=entries(items), advanced=entries(advanced))
