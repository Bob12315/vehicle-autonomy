'use strict';
window.VAF = {
  catalog: [], target: '',
  nodeTypes: {
    Action:['动作执行','执','调用车辆或外部动作'], Sequence:['顺序执行','序','依次执行所有子节点'],
    Parallel:['并行执行','并','按策略协调多个分支'], Condition:['条件判断','判','真 / 假 / 未知三值判断'],
    Fallback:['失败备选','备','安全失败后尝试备选'], Recovery:['故障恢复','复','可信退出后执行恢复'],
    Event:['事件触发','事','等待新的有效事件'], Reactive:['事件响应','应','事件到达后切换分支'],
    Wait:['等待','等','等待指定时长'], Timeout:['超时限制','限','限制子节点执行时长'], Repeat:['有限重复','循','按次数重复子节点']
  },
  actionNames:{GetVehicleState:'读取车辆状态',SetMode:'切换模式',Arm:'解锁',Disarm:'上锁',Takeoff:'起飞',Drive:'直线行驶',Turn:'转向',Goto:'前往目标',Stop:'停止运动',SetVelocity:'设置速度',SetYaw:'设置航向',Hold:'保持位置',ReturnHome:'返回起点',Land:'降落',SetGuidedTarget:'设置固定翼目标',Loiter:'盘旋等待',RTL:'原生返航',AutoLand:'自动着陆'},
  stateNames:{IDLE:'待执行',VALIDATING:'校验中',WAITING:'等待中',READY:'就绪',STARTING:'启动中',RUNNING:'运行中',CANCELLING:'正在请求退出',SUCCEEDED:'已成功',COMPLETED:'已完成',FAILED:'失败',REJECTED:'已拒绝',CANCELLED:'已取消',TIMED_OUT:'已超时',UNKNOWN:'未知',UNCONFIRMED:'未确认'},
  fieldNames:{mode:'飞行 / 驾驶模式',height_m:'起飞高度（米）',x_m:'东向位置 E（米）',y_m:'北向位置 N（米）',z_m:'向上高度 U（米）',speed_mps:'行驶速度（米/秒）',yaw_rate_rad_s:'转向角速度（弧度/秒）',vx_mps:'X 方向速度（米/秒）',vy_mps:'Y 方向速度（米/秒）',vz_mps:'Z 方向速度（米/秒）',yaw_rad:'航向角（弧度）',frame:'坐标系',latitude_deg:'纬度（度）',longitude_deg:'经度（度）',altitude_amsl_m:'海拔高度 AMSL（米）',timeout_s:'超时（秒）',duration_s:'等待时长（秒）',count:'重复次数',output:'输出 Blackboard 键',event:'事件名称',op:'比较运算',source:'数据来源',path:'数据字段路径','value (JSON scalar)':'比较值（JSON 标量）',completion:'并行完成策略',failure:'并行失败策略'},
  typeLabel(type) { return this.nodeTypes[type]?.[0] || type; },
  actionLabel(name) { return window.VAFI18n.text(this.actionNames[name] || name); },
  stateLabel(state) { return window.VAFI18n.text(this.stateNames[state] || state); },
  kindLabel(kind) { return ({rover:'地面车',copter:'多旋翼',plane:'固定翼',OneShot:'单次动作',Goal:'目标动作',Continuous:'持续动作',Query:'只读查询'})[kind] || kind; },
  fieldLabel(name) { return this.fieldNames[name] || window.VAFI18n.field(name); },
  connection(label, state) {
    const el=document.querySelector('#connection-state');if(el){el.textContent=label;el.dataset.state=state;}
  },
  async call(path, payload) { return window.VAFAuth.api(path,payload); },
  node(tag, text, attrs={}) {
    const e = document.createElement(tag); if(tag==='option'&&text!==undefined&&!('value'in attrs))e.setAttribute('value',text);if (text !== undefined) e.textContent = window.VAFI18n.text(text);
    for (const [k,v] of Object.entries(attrs)) e.setAttribute(k,v); return e;
  },
  report(error) { const display=document.querySelector('#notice');display.textContent=window.VAFI18n.error(error.originalMessage||error.message||error);display.title='原始诊断：'+(error.originalMessage||error.message||error); },
  async connect() {
    const vehicles = await this.call('/api/vehicles');
    const select = document.querySelector('#target'); select.replaceChildren();
    for (const v of vehicles) select.append(this.node('option', `${this.kindLabel(v.kind)} · ${v.target}`, {value:v.target}));
    if (!vehicles.length) throw Error('没有可用的自有仿真车辆，请先使用明确的仿真清单启动服务。');
    this.target = select.value;
    await this.loadCatalog(); this.connection('已连接 · '+vehicles.length+' 辆仿真车辆','connected');return vehicles;
  },
  async loadCatalog() { this.target=document.querySelector('#target').value; this.catalog=await this.call('/api/actions?target='+encodeURIComponent(this.target)); },
  parameters(container, schema, values, onChange) {
    container.replaceChildren();
    for (const [name, property] of Object.entries(schema.properties || {})) {
      const label=this.node('label', this.fieldLabel(name)); let input;
      if (values[name] && typeof values[name]==='object' && values[name].$query) {
        input=this.node('input');input.value=JSON.stringify(values[name]);input.readOnly=true;
        input.title='类型化观测参数绑定，可在任务 JSON 中编辑';label.append(input);container.append(label);continue;
      }
      if (property.enum) {
        input=this.node('select'); for (const v of property.enum) input.append(this.node('option',String(v),{value:JSON.stringify(v)}));
        input.value=JSON.stringify(values[name] ?? property.default ?? property.enum[0]);
      } else {
        input=this.node('input'); input.type=property.type==='boolean'?'checkbox':property.type==='string'?'text':'number';
        if(input.type==='checkbox') input.checked=values[name] ?? property.default ?? false;
        else input.value=values[name] ?? property.default ?? property.const ?? '';
        if(property.minimum!==undefined) input.min=property.minimum;
        if(property.maximum!==undefined) input.max=property.maximum;
        if(input.type==='number') input.step=property.type==='integer'?'1':'any';
      }
      input.name=name; input.title=property.description || '';input.required=(schema.required||[]).includes(name);
      if(property.const!==undefined) input.disabled=true;
      const read=()=>property.enum?JSON.parse(input.value):input.type==='checkbox'?input.checked:input.type==='number'?(input.validity?.badInput?NaN:input.value.trim()===''?undefined:Number(input.value)):input.value;
      values[name]=read(); input.addEventListener('change',()=>{ values[name]=read(); if(onChange)onChange(); });
      label.append(input); container.append(label);
    }
  },
  validateParameters(schema,values,allowQueries=false) {
    for(const [name,p] of Object.entries(schema.properties||{})){
      const value=values[name],missing=value===undefined||value===null||value==='';
      if(missing){if((schema.required||[]).includes(name))throw Error('请填写'+this.fieldLabel(name)+'。');continue;}
      if(allowQueries&&typeof value==='object'&&value.$query)continue;
      if(p.type==='number'||p.type==='integer'){
        if(typeof value!=='number'||!Number.isFinite(value)||(p.type==='integer'&&!Number.isInteger(value)))throw Error(this.fieldLabel(name)+'需要有效数字。');
        if((p.minimum!==undefined&&value<p.minimum)||(p.maximum!==undefined&&value>p.maximum))throw Error(this.fieldLabel(name)+'超出允许范围。');
      }
    }
  },
  guard(fn) { return async (...args)=>{try {document.querySelector('#notice').textContent=''; return await fn(...args);}catch(e){this.report(e);}}; }
};
