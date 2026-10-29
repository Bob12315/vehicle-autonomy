'use strict';
// Shared Chinese presentation vocabulary. Never translate wire values, editable
// data, identifiers, JSON or external logs; authentication below stays independent.
window.VAFI18n=(()=>{
 const labels={
  'Vehicle Autonomy':'车辆自主系统','VEHICLE AUTONOMY FRAMEWORK':'车辆自主系统框架','OPERATOR CONSOLE':'操作控制台','OPERATOR CONSOLE · V1':'操作控制台 · 第一版','SECURE OPERATOR SESSION':'统一安全登录',
  'Dashboard':'车辆总览','Vehicle Control':'车辆控制','Mission Studio':'任务编排','Mission Library':'任务库','Mission Editor':'任务编辑器','Mission Runner':'任务运行监控','Mission History':'任务历史',
  'MISSION STUDIO · B':'任务编排 · B版','MISSION STUDIO':'任务编排','MISSION WORKSPACE':'任务工作区','OPERATIONS / VEHICLE CONTROL':'车辆操作与控制','SEND CONTROL':'指令发送控制',
  'Tool Manager':'工具管理','Workspaces':'工作区','Workspace':'工作区','Logs':'日志','Settings':'设置','Action Lab':'动作实验室','Action Library':'动作库','Node Properties':'节点属性','Template Library':'模板库',
  'Editor':'编辑器','Runner':'运行监控','History':'历史记录','Templates':'模板','Inspector':'数据检查','Execution Events':'执行事件','Diagnostics':'诊断','Definition':'任务定义','Basic':'基础','Advanced':'高级',
  'Blackboard':'共享变量','SubMission':'子任务','Mission':'任务','Action':'动作','Agent':'代理程序','Profile':'运行配置','Vehicle Context':'车辆上下文','Vehicle Status':'车辆状态','Safety & Command Feedback':'安全与指令反馈',
  'Control Authority':'控制权','Observer':'只读观察','Acquire Control':'申请控制权','Manual Control':'手动控制','Mode':'模式','Armed':'解锁状态','ROLL':'横滚','PITCH':'俯仰','YAW':'偏航',
  'Launch':'启动','Stop':'停止','Restart':'重启','Configure':'配置','Dependencies':'依赖检查','Connection':'连接信息','Open Window':'打开窗口','Open RViz2':'打开 RViz2','Observe / Connection Info':'观察与连接信息',
  'TOOL / VERSION':'工具 / 版本','HOST / PROFILE':'主机 / 运行配置','INSTALL / PROCESS':'安装 / 进程','HEALTH / READY':'健康 / 就绪','CONNECTION / ERROR':'连接 / 错误','OPERATIONS':'操作',
  'COMPONENT':'组件','AGENT / TOOL / PROFILE':'代理 / 工具 / 运行配置','DEPENDENCIES':'依赖项','READINESS':'就绪状态','Component ID':'组件标识',
  'Installed':'已安装','Missing Dependency':'缺少依赖','Not Installed':'未安装','Not Available':'不可用','Not Running':'未运行','Not Ready':'未就绪','Degraded':'状态降级','Online':'在线','Offline':'离线','Connected':'已连接','Disconnected':'已断开',
  'Ready':'已就绪','Starting':'启动中','Running':'运行中','Failed':'失败','Unknown':'未知','Draft':'草稿','Validated':'已验证','Published':'已发布','TEMPLATE':'模板',
  'IDLE':'待执行','PENDING':'待执行','VALIDATING':'验证中','WAITING':'等待中','READY':'已就绪','STARTING':'启动中','RUNNING':'运行中','CANCELLING':'正在安全退出','STOPPING':'停止中',
  'SUCCEEDED':'已成功','COMPLETED':'已完成','FAILED':'失败','REJECTED':'已拒绝','CANCELLED':'已取消','TIMED_OUT':'已超时','UNKNOWN':'未知','UNCONFIRMED':'未确认','DISCONNECTED':'已断开','STOPPED':'已停止',
  'HEALTHY':'健康','UNHEALTHY':'不健康','VALID':'有效','INVALID':'无效','STALE':'已过期','EXPIRED':'已过期','ABSENT':'无数据','UNAVAILABLE':'不可用','UNKNOWN_CAPTURE_TIME':'采样时间未知',
  'PAUSED':'已暂停','PAUSE_REQUESTED':'已请求安全暂停','TAKEOVER_REQUESTED':'已请求接管','SUSPENDED':'已挂起','SKIPPED':'已跳过','SAVED':'已保存','PUBLISHED':'已发布','ABANDONED':'已放弃','SWITCHING':'切换中',
  'OBSERVER':'只读观察','MANUAL_CONTROL':'手动控制','RELEASING':'正在释放','QUEUED':'已排队','ACCEPTED':'已接受','SENT':'已发送','ACKNOWLEDGED':'已应答','RECEIVED':'已接收','PREPARING':'准备中','BLOCKED':'受阻',
  'OneShot':'单次动作','Goal':'目标动作','Continuous':'持续动作','Query':'只读查询','Start':'开始','End':'结束','Wait':'等待','Condition':'条件判断','ForEach':'逐项循环','Parallel':'并行','Join':'分支汇合','Sequence':'顺序执行','Recovery':'故障恢复','Retry':'有限重试','Fallback':'失败备选','Event':'事件触发','Reactive':'事件响应','Timeout':'超时限制','Repeat':'有限重复',
  'flow':'流程','logic':'逻辑','action':'动作','loop':'循环','parallel':'并行','wait':'等待','composite':'复合','next':'下一步','body':'循环体','failure':'失败','try':'尝试','recover':'恢复','true':'是','false':'否','unknown':'未知',
  'rover':'地面车','copter':'多旋翼','plane':'固定翼','Rover':'地面车','Copter':'多旋翼','Plane':'固定翼','simulation':'仿真','hardware_readonly':'实机只读','monitor':'遥测监视',
  'GUIDED':'引导（GUIDED）','HOLD':'保持（HOLD）','LOITER':'盘旋保持（LOITER）','RTL':'原生返航（RTL）','MANUAL':'手动（MANUAL）','AUTO':'自动（AUTO）','BRAKE':'制动（BRAKE）','LAND':'降落（LAND）','STABILIZE':'姿态稳定（STABILIZE）',
  'ARMED':'已解锁','DISARMED':'已上锁','Disarmed':'已上锁','ARM':'解锁','DISARM':'上锁','STOP':'停止','RETURN HOME':'返回起点','ON':'开启','OFF':'关闭','SEND ON':'开启指令发送','SEND OFF':'关闭指令发送',
  'GetVehicleState':'读取车辆状态','SetMode':'切换模式','Arm':'解锁','Disarm':'上锁','Takeoff':'起飞','Drive':'直线行驶','Turn':'转向','Goto':'前往目标','SetVelocity':'设置速度','SetYaw':'设置航向','Hold':'保持位置','ReturnHome':'返回起点','Land':'降落','SetGuidedTarget':'设置固定翼目标','Loiter':'盘旋保持','AutoLand':'自动着陆',
  'Sim.PreflightCheck':'仿真：任务预检','Sim.ObserveArea':'仿真：观察区域','Sim.DetectContainers':'仿真：检测容器','Sim.SelectTargets':'仿真：选择目标','Sim.ConfirmTarget':'仿真：确认目标','Sim.SimulatedTaskOperation':'仿真：记录模拟操作','Sim.RecoverLostTarget':'仿真：丢失目标恢复','Sim.ReturnAndLand':'仿真：记录返航降落',
  'HandleTarget':'处理目标','Preflight':'起飞前检查','Safety Check':'安全检查','Debug Run':'调试运行','Diff':'差异比较','Boolean':'布尔值','Integer':'整数','Float':'小数','String':'文本','boolean':'布尔值','integer':'整数','number':'数值','string':'文本','object':'对象','array':'列表','null':'空值',
  'all':'全部完成','any':'任一完成','main':'主分支完成','abort':'终止','continue':'继续','branch':'失败分支','retry':'重试','duration':'固定时长','condition':'条件等待','event':'事件等待','set':'赋值','append':'追加','fixed':'固定值',
  'eq':'等于','ne':'不等于','lt':'小于','le':'小于等于','gt':'大于','ge':'大于等于','not':'非','world':'外部状态','blackboard':'共享变量',
  'EXTERNAL · observe only':'外部进程 · 仅观察','SITL / Simulation':'飞控软件仿真','Real hardware · receive only':'真实硬件 · 仅接收','Hardware-Ready':'硬件就绪软件验证',
  'REGISTERED_IN_PROCESS':'进程内已注册','BOUND_EXTERNAL':'外部服务已绑定','checked at Action admission':'动作准入时检查','no verified external Provider binding':'没有可验证的外部服务绑定',
  'Only current odom position proposals. Orientation and unqualified map transforms are not imported. QGC import is not installed.':'仅导入当前有效的里程计位置目标；不导入方向或未经验证的地图变换。尚未接入地面站目标导入。'
 };
 Object.assign(labels,{
  "RViz Pending Goals": "RViz 待确认导航目标",
  "Safety & Authority": "安全与控制权",
  "Command Feedback": "指令反馈",
  "Diagnostics / Logs": "诊断与日志",
  "STOP CURRENT OWNER": "安全退出当前控制者",
  "Vehicle ID / Type": "车辆标识 / 类型",
  "Flight Mode": "飞控模式",
  "Battery": "剩余电量",
  "Voltage": "电池电压",
  "Ground Speed": "地速",
  "Airspeed": "空速",
  "Altitude · odom U": "相对高度 · 里程计向上轴",
  "Heading · N / CW": "航向 · 北向起顺时针",
  "GPS Fix / Satellites": "卫星定位等级 / 卫星数",
  "Telemetry": "遥测新鲜度",
  "Execution Lease": "执行控制租约",
  "LIVE · WebSocket": "实时连接 · WebSocket",
  "MAVLink · Connected": "MAVLink · 已连接",
  "MAVLink · Disconnected": "MAVLink · 已断开",
  "STALE / UNKNOWN": "已过期 / 未知",
  "Launch Workspace": "启动工作区",
  "Stop Workspace": "停止工作区",
  "Restart Workspace": "重启工作区",
  "Save Workspace": "保存工作区",
  "YES": "是",
  "NO": "否",
  "Stopping": "停止中",
  "desktop": "桌面端",
  "server": "服务器端",
  "onboard": "车载端",
  "Desktop": "桌面端",
  "Server": "服务器端",
  "Onboard": "车载端",
  "Tool": "工具",
  "Runtime": "运行时",
  "Registry": "注册表",
  "Scope": "执行范围",
  "Lease": "控制租约",
  "Failsafe": "失效保护",
  "CONNECTING": "连接中",
  "TRANSMITTED": "已发送",
  "SUPPORTED": "已支持",
  "UNSUPPORTED": "不支持",
  "Read immutable world, including freshness; grants no authority.": "读取不可变状态快照及其新鲜度，不授予控制权。",
  "Command COMPLETED plus authenticated post-request target state; mode adoption is not arrival.": "命令完成后，还需验证请求之后的真实目标状态；模式生效不代表已抵达。",
  "Copter: measured climb +/-0.35 m, settled 2 s. Plane: 50 +/-5 m and 8..28 m/s, settled 2 s; flight remains reserved.": "多旋翼：实测高度误差不超过 0.35 米，稳定 2 秒。固定翼：高度 50±5 米、速度 8～28 米/秒，稳定 2 秒；仍保留飞行控制占用。",
  "Continuous body setpoints until explicit cancel. Exit zeros the old stream, requests native HOLD and requires the existing observed stop barrier. New movement requires GUIDED again.": "持续发送车体目标，直至明确取消。退出时旧目标流归零，切入保持模式并等待实测停车确认；再次运动需重新切入引导模式。",
  "Existing spatial arrival, stability and stop barriers; ACK is not arrival.": "以现有空间到达、稳定和停止条件确认完成；飞控应答不等于到达。",
  "Native HOLD confirmation plus fresh observed speed <=0.1 m/s settled 2 s; does not require entering GUIDED to stop.": "确认保持模式生效，并以新鲜遥测验证速度不超过 0.1 米/秒、稳定 2 秒；停车不要求先进入引导模式。",
  "SetYaw: observed yaw within 0.1 rad settled 1 s; continuous operations require explicit cancellation.": "航向动作：实测角度误差不超过 0.1 弧度，稳定 1 秒；持续动作需要明确取消。",
  "Rover: actual home <=0.75 m, <=0.1 m/s settled 2 s, native HOLD exit. Copter: observed touchdown and disarmed.": "地面车：实测距起点不超过 0.75 米、速度不超过 0.1 米/秒，稳定 2 秒后保持停车。多旋翼：观察到着陆并上锁。",
  "Observed ground, disarm and stability; native ACK is insufficient.": "必须观察到落地、上锁及稳定状态；仅有飞控应答不足以确认完成。",
  "AutoLand: actual ground <0.25 m, speed <1 m/s settled 3 s and authenticated disarm. Other operations confirm configuration only; flight remains reserved.": "自动着陆：实测离地高度小于 0.25 米、速度小于 1 米/秒，稳定 3 秒并确认上锁。其他操作只确认配置生效，仍保留飞行控制占用。",
  "Plane: native RTL mode adoption, not arrival or landing. Rover/Copter: physical ReturnHome goal.": "固定翼：只确认原生返航模式生效，不代表到达或着陆。地面车和多旋翼：以真实返航到达条件确认。",
  "Native Goal result AND independent fresh World map pose, followed by parked vehicle and stopped native producer cohort.": "原生导航结果和独立的新鲜地图位姿均须满足，随后确认车辆停车且导航生产者已停止。"
});
 Object.assign(labels,{
  "Exit barrier; uncertain physical effects retain resources.": "请求安全退出并等待确认；物理影响未确认时继续保留资源。",
  "Relative Altitude": "相对高度",
  "ACTIVE": "有效",
  "SEND": "指令发送",
  "Runner": "运行监控",
  "Schema": "类型定义",
  "Frame": "坐标系",
  "Fix": "定位等级",
  "Flags": "标志位"
});
 Object.assign(labels,{
  "CUADC MultiTarget · 纯软件模拟": "CUADC 多目标 · 纯软件模拟",
  "HandleTarget · 软件仿真": "处理目标 · 软件仿真",
  "blackboard_written": "共享变量已写入",
  "mission_started": "任务已启动",
  "node_state": "节点状态变化",
  "breakpoint_reached": "已到达断点",
  "mission_step": "任务单步",
  "mission_resume": "任务已恢复",
  "mission_suspended": "任务已挂起",
  "mission_finished": "任务已结束",
  "mission_cancel_requested": "已请求取消任务",
  "suspended_mission_cancelled": "已取消挂起任务",
  "action_intent": "已提交动作意图",
  "iteration_completed": "循环项已完成",
  "event_consumed": "事件已处理",
  "takeover_blocked": "接管被阻止",
  "takeover_requested": "已请求接管",
  "pause_requested": "已请求安全暂停",
  "breakpoints_changed": "断点已修改",
  "debug_failure": "调试失败",
  "debug_retry": "调试重试",
  "debug_skip": "调试跳过",
  "debug_override": "调试参数已覆盖"
});
 const fields={mode:'飞控模式',height_m:'起飞高度（米）',x_m:'东向位置（米）',y_m:'北向位置（米）',z_m:'向上高度（米）',vx_mps:'前向速度（米/秒）',vy_mps:'左向速度（米/秒）',vz_mps:'向上速度（米/秒）',speed_mps:'速度（米/秒）',yaw_rate_rad_s:'偏航角速度（弧度/秒）',yaw_rad:'航向角（弧度）',frame:'坐标系',latitude_deg:'纬度（度）',longitude_deg:'经度（度）',altitude_amsl_m:'海拔高度（米）',duration_s:'等待时长（秒）',timeout_s:'超时（秒）',count:'次数',source:'数据来源',path:'字段路径',op:'比较方式',value:'值',target:'目标',position:'位置',orientation:'姿态',remaining:'剩余数量',detections:'检测结果',selected_targets:'已选目标',current_target:'当前目标',results:'结果',mission_status:'任务状态',simulated_payload_slot:'模拟任务槽位',remaining_in:'输入剩余数量',remaining_out:'输出剩余数量',operation_status:'操作状态',task_result:'任务结果',simulate_target_loss:'模拟目标丢失',physical_diameter_m:'物理直径（米）',physical_size_source:'物理尺寸来源',bbox_area_px:'像素框面积',valid:'有效',lose_on_confirmation:'确认时模拟丢失',parameters:'参数',input_bindings:'输入绑定',output_bindings:'输出绑定',execution_policy:'执行策略',failure_policy:'失败策略',supported_vehicles:'支持车型',metadata:'元数据',interface:'输入输出接口',max_iterations:'最大循环次数',on_item_failure:'单次失败策略',max_concurrency:'最大并发数',completion:'完成策略',join_id:'汇合节点标识',collection:'循环集合',schema:'类型定义',readonly:'只读',max_age_s:'最长有效期（秒）',unit:'单位',origin:'参考原点',default:'默认值',name:'名称',version:'版本',mission_id:'任务标识',node_id:'节点标识',template_id:'模板标识',template:'模板',sub_mission_id:'子任务标识'};
 const terms={'Mission Studio':'任务编排','Mission Library':'任务库','Mission Editor':'任务编辑器','Action Lab':'动作实验室','Tool Manager':'工具管理','Open Window':'打开窗口','SEND ON':'开启指令发送','SEND OFF':'关闭指令发送','SubMission':'子任务','Blackboard':'共享变量','Workspace':'工作区','Profile':'运行配置','Provider':'能力服务','Agent':'代理程序','Mission':'任务','Action':'动作','Armed':'解锁状态','Mode':'模式','Observer':'只读观察','Rover':'地面车','Copter':'多旋翼','Plane':'固定翼','Starting':'启动中','Ready':'已就绪','Scope':'执行范围','Lease':'控制租约','Failsafe':'失效保护','Fix':'定位等级','Flags':'标志位','watchdog':'看门狗','Bridge':'数据桥接','Namespace':'命名空间','Domain':'域编号','Hardware-Ready':'硬件就绪软件验证'};
 // Only known UI tokens are translated. Values in editable fields and raw evidence remain untouched.
 for(const [key,label]of Object.entries(labels))if(/^[A-Z][A-Za-z_ ]*$/.test(key)&&!/[A-Za-z]/.test(label))terms[key]=label;
 const tokenEntries=Object.entries(terms).sort((a,b)=>b[0].length-a[0].length);
 function text(value){if(value===undefined||value===null)return value;const raw=String(value),trim=raw.trim();let out=labels[trim]??fields[trim];if(out!==undefined)return raw.replace(trim,out);if(/^(branch|child):[0-9]+$/.test(trim))return (trim.startsWith('branch')?'分支 ':'步骤 ')+(Number(trim.split(':')[1])+1);if(trim.startsWith('Mode · '))return '模式 · '+text(trim.slice(7));{out=raw;for(const [a,b]of tokenEntries)out=out.replace(new RegExp('\\b'+a+'\\b','g'),b);return out;}}
 function field(value){return fields[value]||text(value);}
 function error(value){let raw=String(value||'');const exact={'invalid access key':'访问密钥无效','invalid login key':'访问密钥无效','Failed to fetch':'连接失败，请检查服务是否在线','Load failed':'连接失败，请检查服务是否在线','NetworkError when attempting to fetch resource.':'网络连接失败','invalid key':'访问密钥无效','invalid credentials':'认证凭据无效','authentication required':'请先登录','session expired':'登录会话已过期','request body too large':'请求内容过大'};if(exact[raw])return exact[raw];if(/[\u3400-\u9fff]/.test(raw))return text(raw);const rules=[[/draft revision conflict/i,'草稿已被另一编辑器修改，请重新加载或合并'],[/published version immutable/i,'发布版本不可修改，请使用新的版本号'],[/telemetry.*stale|fresh.*state|fresh.*telemetry/i,'遥测已过期或无效，请等待新鲜有效的车辆状态'],[/Mission owns|target owned|resource conflict|Web control reserved/i,'目标或资源已被占用，请先安全释放原控制'],[/safe paused boundary/i,'操作需要先到达已确认的安全暂停点'],[/unconfirmed|physical exit|exit barrier/i,'物理退出尚未确认，当前操作被阻止'],[/missing required/i,'缺少必填参数，请检查节点配置'],[/type mismatch|expected (integer|number|object|string|array)/i,'数据类型不匹配，请检查参数和变量绑定'],[/unreachable|dangling|unsupported.*port/i,'任务图包含不可达节点或无效连线'],[/recursive|recursion/i,'子任务存在递归引用'],[/Provider not bound|provider unavailable/i,'能力服务未绑定或不可用'],[/expired|stale.*binding/i,'输入数据已过期，请重新选择或刷新'],[/unknown vehicle|unsupported.*vehicle|capability unavailable/i,'车辆未装配或不支持该能力'],[/CSRF|origin|unauthorized|forbidden|authentication|invalid.*key/i,'认证或安全校验未通过，请重新登录'],[/timeout|timed out|aborted/i,'请求超时，请刷新状态后重试'],[/Plane.*single-step/i,'固定翼控制任务不支持运动单步，请整体运行或安全退出'],[/checkpoint resume|interrupted Action/i,'活动动作已被中断，不能直接恢复；请创建重新验证的运行']];for(const [pattern,label]of rules)if(pattern.test(raw))return label;return '操作未完成，请查看原始诊断信息。';}
 function install(){const skip='script,style,pre,code,textarea,input,[contenteditable="true"],[data-original-text]';function translate(root){if(!root)return;const visit=n=>{const parent=n.parentElement;if(!parent||parent.closest(skip))return;const next=text(n.data);if(next!==n.data){if(parent.tagName==='OPTION'&&!parent.hasAttribute('value'))parent.setAttribute('value',parent.textContent);n.data=next;}};if(root.nodeType===3){visit(root);return;}if(root.nodeType!==1||root.closest(skip))return;for(const attr of ['title','aria-label','placeholder'])if(root.hasAttribute(attr)){const old=root.getAttribute(attr),next=attr==='title'&&/^原始(诊断|契约)：/.test(old)?old:text(old);if(next!==old)root.setAttribute(attr,next);}for(const element of root.querySelectorAll('[title],[aria-label],[placeholder]'))if(!element.closest(skip))for(const attr of ['title','aria-label','placeholder'])if(element.hasAttribute(attr)){const old=element.getAttribute(attr),next=attr==='title'&&/^原始(诊断|契约)：/.test(old)?old:text(old);if(next!==old)element.setAttribute(attr,next);}const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let n;while(n=walker.nextNode())visit(n);}
  translate(document.documentElement);new MutationObserver(records=>{for(const r of records){if(r.type==='characterData')translate(r.target);else if(r.type==='attributes')translate(r.target);else for(const n of r.addedNodes)translate(n);}}).observe(document.documentElement,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['title','aria-label','placeholder']});}
 if(document.documentElement)install();return {text,field,error,labels,fields};
})();
// Only the server holds the management key. Pages share an HttpOnly cookie.
window.VAFAuth=(()=>{
 let session=null,control='',redirecting=false;
 const channel=typeof BroadcastChannel==='function'?new BroadcastChannel('vaf-auth'):null;
 const next=()=>location.pathname+location.search+location.hash;
 function lost(){
  session=null;control='';window.dispatchEvent(new Event('vaf:auth-lost'));
  if(!redirecting&&location.pathname!=='/login'){redirecting=true;location.replace('/login?next='+encodeURIComponent(next()));}
 }
 if(channel)channel.onmessage=e=>{if(e.data==='logout')lost();};
 async function restore(){
  const r=await fetch('/api/auth/session',{credentials:'same-origin',cache:'no-store'});
  if(!r.ok){if(location.pathname!=='/login')lost();return null;}
  const data=await r.json();session=data.result;return session;
 }
 const ready=restore();
 async function api(path,payload){
  await ready;if(!session)throw Error('请先登录');
  const headers={};const options={credentials:'same-origin',cache:'no-store',headers,signal:AbortSignal.timeout(5000)};
  if(payload!==undefined){Object.assign(headers,{'Content-Type':'application/json','X-VAF-CSRF':session.csrf,'X-VAF-Request-ID':crypto.randomUUID()});options.method='POST';options.body=JSON.stringify(payload);}
  if(control)headers['X-VAF-Control']=control;
  const r=await fetch(path,options);const value=await r.json();
  if(r.status===401){lost();throw Error('登录已失效，请重新登录');}
  if(!r.ok||!value.ok){const original=value.error||'请求失败',error=Error(window.VAFI18n.error(original));error.originalMessage=original;error.status=r.status;error.response=value;throw error;}return value.result;
 }
 async function logout(){
  await api('/api/auth/logout',{});if(channel)channel.postMessage('logout');lost();
 }
 document.addEventListener('DOMContentLoaded',()=>{
  for(const button of document.querySelectorAll('[data-logout]'))button.onclick=()=>logout().catch(lost);
 });
 return {ready,api,logout,get session(){return session;},get control(){return control;},set control(value){control=value||'';},lost};
})();
