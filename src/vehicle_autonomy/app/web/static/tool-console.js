'use strict';
const $=s=>document.querySelector(s),node=(tag,text,attrs={})=>{const e=document.createElement(tag);if(tag==='option'&&text!==undefined&&!('value'in attrs))e.setAttribute('value',text);if(text!==undefined)e.textContent='data-original-text'in attrs?text:window.VAFI18n.text(text);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);return e;};
let snapshot=null,connected=false,busy=false,vehicleId='',kindFilter='',view='dashboard',lastReceived=0,settingsLoaded=false,detailSelection=null;
const profileSelections=new Map();
let workspaceDraft=null;
const titles={dashboard:['车辆总览','遥测、执行状态与控制权，来自同一受控运行时。'],tools:['工具管理','选择运行主机，管理外部软件的生命周期与真实连接状态。'],workspaces:['工作环境','按声明的依赖准备工具，保留共享服务的所有权。'],logs:['日志与诊断','追踪工具启动、进程输出、失败和认证操作记录。'],settings:['设置','配置车辆上下文与已注册的工具 Profile。']};
const kindNames={rover:'地面车',copter:'多旋翼',plane:'固定翼'};
let toolContext={vehicle_id:'rover',vehicle_type:'rover',environment:'simulation',ros_namespace:'/rover',ros_domain_id:91,mavlink_profile:'monitor'};
const num=(v,d=2)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(d):'未知';
const vector=v=>v?`X ${num(v.x)} / Y ${num(v.y)} / Z ${num(v.z)}`:'未知';
const badge=(text,tone='')=>node('span',text,{class:'badge','data-tone':tone});
function notice(e){$('#notice').textContent=e?.message||String(e||'');$('#notice').dataset.tone=e?.message?'error':'info';}
function guard(fn){return async(...args)=>{try{await fn(...args);}catch(e){notice(e);}};}
async function api(path,payload){return window.VAFAuth.api(path,payload);}
function route(){view=location.hash.slice(1)||'dashboard';if(!titles[view])view='dashboard';for(const e of document.querySelectorAll('[data-panel]'))e.hidden=e.dataset.panel!==view;for(const e of document.querySelectorAll('[data-view]')){if(e.dataset.view===view)e.setAttribute('aria-current','page');else e.removeAttribute('aria-current');}$('#page-title').textContent=titles[view][0];$('#page-subtitle').textContent=titles[view][1];if(snapshot)render();}
window.addEventListener('hashchange',route);route();
function linkState(ok){$('#link-state').textContent=ok?'控制中心已连接':'控制中心已断开 · 状态未知';$('#link-dot').style.background=ok?'#087e79':'#ad3c32';}
function invalidate(){if(!snapshot)return;snapshot.vehicles=[];if(snapshot.tools){for(const a of snapshot.tools.agents){a.connected=false;for(const t of a.tools)if(t.instance)Object.assign(t.instance,{state:'DISCONNECTED',ready:false,process_running:null,service_health:'UNKNOWN',connection:'DISCONNECTED'});}for(const r of snapshot.tools.workspaces?.runs||[])if(!['STOPPED','ABANDONED'].includes(r.state)){r.state='UNKNOWN';r.error='Web 连接中断，远端状态未知';for(const c of r.components)c.observed_ready=false;}}$('#tool-detail').hidden=true;renderTools();renderWorkspaces();$('#dashboard-data').hidden=true;$('#vehicle-empty').hidden=false;$('#vehicle-empty').replaceChildren(node('strong','连接中断，当前状态未知'),node('p','连接恢复后同步完整状态。已显示的旧遥测不能用于操作。'));linkState(false);}
async function poll(){if(busy||!connected)return;busy=true;try{snapshot=await api('/api/console/state');if(!settingsLoaded&&snapshot.tools?.settings){toolContext=snapshot.tools.settings.context;fillContext();settingsLoaded=true;}lastReceived=performance.now();linkState(true);$('#updated').textContent='已同步 '+new Date().toLocaleTimeString('zh-CN',{hour12:false});render();}catch(e){invalidate();notice(e);}finally{busy=false;}}
$('#reconnect').onclick=guard(async()=>{connected=true;notice('');await poll();});
window.addEventListener('vaf:auth-lost',()=>{connected=false;invalidate();});
window.VAFAuth.ready.then(s=>{if(s){connected=true;poll();}});
setInterval(()=>{if(connected)poll();if(lastReceived&&performance.now()-lastReceived>4500)invalidate();},750);
function selectContext(v){if(!v)return;const changed=toolContext.vehicle_id!==v.id;toolContext={...toolContext,vehicle_id:v.id,vehicle_type:v.type,environment:v.environment==='simulation'?'simulation':'hardware_readonly',ros_namespace:changed?'/'+v.id.replace(/[^A-Za-z0-9_]/g,'_'):toolContext.ros_namespace};fillContext();}
$('#vehicle').onchange=()=>{vehicleId=$('#vehicle').value;selectContext(snapshot?.vehicles.find(v=>v.id===vehicleId));render();};
for(const b of document.querySelectorAll('[data-kind]'))b.onclick=()=>{kindFilter=b.dataset.kind;for(const x of document.querySelectorAll('[data-kind]'))x.setAttribute('aria-pressed',String(x===b));render();};
function list(target,items){target.replaceChildren();for(const[k,v]of items){const row=node('div');row.append(node('dt',k),node('dd',v??'未知'));target.append(row);}}
function render(){
 const available=snapshot.vehicles.filter(v=>!kindFilter||v.type===kindFilter),select=$('#vehicle');
 if(!available.some(v=>v.id===vehicleId)){vehicleId=available.find(v=>v.id===toolContext.vehicle_id)?.id||available[0]?.id||'';selectContext(available.find(v=>v.id===vehicleId));}
 select.replaceChildren(...available.map(v=>node('option',`${kindNames[v.type]} / ${v.id}`,{value:v.id})));select.value=vehicleId;if(!available.length)select.append(node('option','未装配所选车型',{value:''}));
 const v=available.find(v=>v.id===vehicleId);$('#vehicle-empty').hidden=!!v;$('#dashboard-data').hidden=!v;
 $('#environment').textContent=v?(v.environment==='simulation'?'SITL · 自有仿真':'车辆环境未验证'):'无车辆 · 工具可独立运行';
 $('#vehicle-label').textContent=v?`${v.id} / ${kindNames[v.type]}`:'';
 if(v){
  $('#metric-connection').textContent=v.connected?'Connected':'Disconnected';$('#metric-mode').textContent=v.mode||'未知';$('#metric-armed').textContent=v.armed===true?'已解锁':v.armed===false?'未解锁':'未知';$('#metric-age').textContent=v.fresh?num(v.telemetry_age_s,1)+' s · 有效':'过期 / 未知';
  list($('#telemetry'),[['位置 · odom / m',vector(v.position)],['速度 · m/s',vector(v.velocity)],['高度 · odom 向上 / m',num(v.altitude_m)],['航向 · ENU / °',num(v.heading_deg,1)],['姿态 · W / X / Y / Z',v.attitude?['w','x','y','z'].map(k=>num(v.attitude[k])).join(' / '):'未知'],...(v.type==='plane'?[['空速 · m/s',num(v.airspeed_mps)],['WGS84 经纬度',v.global_position?`${num(v.global_position.longitude_deg,6)} / ${num(v.global_position.latitude_deg,6)}`:'未知'],['AMSL 高度 / m',num(v.global_position?.altitude_m)]]:[['定位样本年龄 / s',num(v.pose_age_s,1)]])]);
  $('#health-badge').textContent=v.health?.quality||'UNKNOWN';$('#health-badge').dataset.tone=v.fresh?'good':'warning';
  list($('#health'),[['电池电压 / V',num(v.battery?.voltage_v)],['剩余电量 / %',num(v.battery?.remaining_percent,0)],['GPS',v.gps?.value?`Fix ${v.gps.value.fix_type} / 卫星 ${v.gps.value.satellites??'未知'} · ${v.gps.availability}`:'未知'],['EKF',v.ekf?.value?`Flags ${v.ekf.value.flags} · ${v.ekf.availability}`:'未知'],['Failsafe',v.failsafe===true?'触发':v.failsafe===false?'未触发':'未知'],['飞控消息',v.status_text?.value?.text||'未知'],['系统故障',v.fault||snapshot.fault||(v.health?.faults?.join('; ')||'未报告')]]);
  $('#authority').replaceChildren(...['system_send','action_send','lease_active'].map(k=>node('span',`${{system_send:'系统 SEND',action_send:'Action SEND',lease_active:'Lease'}[k]}: ${v.authority[k]===true?'ON':v.authority[k]===false?'OFF':'UNKNOWN'}`)),node('span','Scope: '+(v.authority.scope||'无')));$('#control-hint').textContent=v.control_hint||'仅显示状态，控制操作需经现有控制台逐次授权。';
  $('#activity').replaceChildren();for(const m of v.missions.slice(-3)){const r=node('div');r.append(node('span','Mission '+m.id),badge(m.state,m.release_safe?'good':'warning'));$('#activity').append(r);}for(const a of v.actions.slice(-3)){const r=node('div');r.append(node('span',a.name),badge(a.state,a.safety?.release_safe?'good':'warning'));$('#activity').append(r);}if(!v.missions.length&&!v.actions.length)$('#activity').append(node('p','暂无运行记录',{class:'muted'}));
 }
 window.VAFVisualization.render($('#visualization-entry'),snapshot,vehicleId);renderTools();renderWorkspaces();renderLogs();$('#settings-info').textContent=JSON.stringify({agents:snapshot.tools?.agents?.map(a=>({id:a.id,role:a.role,connected:a.connected})),poll_interval_ms:750,transport:'Authenticated HTTP / SSH forwarding',vehicle_command_path:'Existing MissionControl / ActionRuntime / Execution'},null,2);
}
function findTool(agentId,toolId){const a=snapshot.tools?.agents.find(a=>a.id===agentId);return[a,a?.tools.find(t=>t.manifest.id===toolId)];}
function button(text,fn,disabled=false,title=''){const b=node('button',text,{type:'button',title});b.disabled=disabled;b.onclick=guard(fn);return b;}
function profileFor(a,t){const key=a.id+':'+t.manifest.id;return profileSelections.get(key)||snapshot.tools.settings.profiles[key]?.profile_id||t.instance?.profile_id||Object.keys(t.manifest.profiles)[0];}
async function operate(agentId,toolId,op){
 const[a,t]=findTool(agentId,toolId);let profile=profileFor(a,t),ctx=toolContext;
 if(['stop','restart'].includes(op)&&t.instance?.owned){profile=t.instance.profile_id;ctx=t.instance.context;}
 const job=await api('/api/tools/operation',{agent_id:a.id,tool_id:toolId,profile_id:profile,operation:op,context:ctx});
 notice(`已排队 ${op} · ${a.id} / ${toolId} · ${job.id.slice(0,8)}，等待 Agent 结果。`);await poll();
}
function renderTools(){
 if(!snapshot.tools)return;
 const host=$('#agents');host.replaceChildren();
 for(const a of snapshot.tools.agents){const row=node('div');row.append(badge(a.connected?'Online':'Disconnected',a.connected?'good':'error'),node('strong',' '+a.name),node('small',`${a.id} · ${a.role} · 心跳 ${num(a.heartbeat_age_s,1)} s`));host.append(row);}
 if(!snapshot.tools.agents.length){$('#tools-content').className='panel empty';$('#tools-content').replaceChildren(node('strong','等待 Agent 上线'),node('p','首次授权后，Agent 每次启动都会自动连接，无需重复手动注册。'));return;}
 if(view!=='tools')return;
 if(snapshot.tools.agents.every(a=>a.connected)&&$('#tools-content').contains(document.activeElement)&&document.activeElement.tagName==='SELECT')return;
 const table=node('table',undefined,{class:'tools-table'}),thead=node('thead'),tr=node('tr');for(const name of ['TOOL / VERSION','HOST / PROFILE','INSTALL / PROCESS','HEALTH / READY','CONNECTION / ERROR','OPERATIONS'])tr.append(node('th',name));thead.append(tr);table.append(thead);const body=node('tbody');table.append(body);
 for(const a of snapshot.tools.agents)for(const t of a.tools){
  const m=t.manifest,p=profileFor(a,t),check=t.checks[p]||{},i=t.instance,key=a.id+':'+m.id;
  const row=node('tr',undefined,{'data-tool':key}),identity=node('td');identity.append(node('strong',m.name),node('small',m.version));row.append(identity);
  const cell=node('td');cell.append(node('strong',a.id));const select=node('select',undefined,{'aria-label':m.name+' Profile'});for(const name of Object.keys(m.profiles))select.append(node('option',name,{value:name}));select.value=p;select.onchange=()=>{profileSelections.set(key,select.value);select.blur();renderTools();};cell.append(node('br'),select);if(i&&i.profile_id!==p)cell.append(node('small','运行中: '+i.profile_id));row.append(cell);
  const process=node('td');process.append(badge(a.connected?(check.installed?'Installed':'Missing Dependency'):'Unknown',a.connected&&check.installed?'good':'warning'));process.append(node('small',a.connected?(i?.state||(t.external_pids.length?'EXTERNAL · observe only':'STOPPED')):'DISCONNECTED'));if(i?.pid)process.append(node('small',`PID ${i.pid} · RSS ${num(i.resource?.rss_bytes/1048576,1)} MiB`));row.append(process);
  const visual=m.integrations.includes('ros2.visualization');
  const readiness=visual?(!a.connected?'Unknown':!check.installed?'Not Installed':!i||i.state==='STOPPED'?'Not Running':i.state==='FAILED'?'Failed':i.state==='STARTING'?'Starting':i.ready?'Ready':i.process_running&&(i.service_health==='UNHEALTHY'||i.connection==='DISCONNECTED')?'Degraded':i.process_running?'Running':'Not Ready'):(a.connected&&i?.ready?'Ready':'Not Ready');
  const health=node('td');health.append(node('span',a.connected?(i?.service_health||'UNKNOWN'):'UNKNOWN'),node('br'),badge(readiness,a.connected&&i?.ready?'good':'warning'));row.append(health);
  const connection=node('td'),last=snapshot.tools.jobs.filter(j=>j.agent_id===a.id&&j.tool_id===m.id).at(-1);connection.append(node('span',a.connected?(i?.connection||'UNKNOWN'):'DISCONNECTED'));const error=(!a.connected?'Agent 失联；远端进程状态未知':i?.error)||(['FAILED','EXPIRED','UNKNOWN'].includes(last?.state)?last.error:null)||check.missing?.join('; ');if(error)connection.append(node('small',error));else connection.append(node('small',i?.context?`车辆 ${i.context.vehicle_id} · ${i.context.ros_namespace}`:`将关联 ${toolContext.vehicle_id}`));row.append(connection);
  const actions=node('td'),buttons=node('div',undefined,{class:'actions'}),active=i?.process_running===true;
  buttons.append(button('Launch',()=>operate(a.id,m.id,'launch'),!a.connected||!check.launchable||active||t.external_pids.length>0,error||'启动选定 Profile'),button('Stop',()=>operate(a.id,m.id,'stop'),!a.connected||!active||!i?.owned,'只停止本 Agent 拥有的进程'),button('Restart',()=>operate(a.id,m.id,'restart'),!a.connected||!i?.owned||!check.launchable),button('Logs',()=>showTool(a.id,m.id,'logs')),button('Configure',()=>showTool(a.id,m.id,'configure')),button('Dependencies',()=>operate(a.id,m.id,'check'),!a.connected),button('Connection',()=>showTool(a.id,m.id,'connection')));
  if(m.type==='gui')buttons.append(button('Open Window',()=>operate(a.id,m.id,'open'),!a.connected||active||!check.launchable,'在目标 Agent 桌面启动；不提供已有远端窗口置前'));
  if(t.external_pids.length)buttons.append(button('Observe / Connection Info',()=>operate(a.id,m.id,'connect'),!a.connected));actions.append(buttons);row.append(actions);body.append(row);
 }
 const container=$('#tools-content');container.className='panel table-wrap';container.replaceChildren(node('p',`启动上下文：${toolContext.vehicle_id} / ${toolContext.vehicle_type} · ${toolContext.environment} · ROS ${toolContext.ros_domain_id} ${toolContext.ros_namespace}`,{class:'muted'}),table);
 if(detailSelection?.mode==='logs'){const[a,t]=findTool(detailSelection.agent,detailSelection.tool);if(t)$('#tool-detail pre').textContent=t.instance?.logs?.join('')||'当前没有由 Agent 收集的进程输出。';}
}
async function showTool(agentId,toolId,mode){
 const[a,t]=findTool(agentId,toolId),p=profileFor(a,t),detail=$('#tool-detail'),selection={agent:agentId,tool:toolId,mode};detailSelection=selection;detail.hidden=false;detail.replaceChildren(node('h2',`${t.manifest.name} / ${a.id}`));
 if(mode==='configure'){
  detail.append(node('p','选择主机预先授权的 Profile。保存选择不会修改正在运行的实例。',{class:'muted'}));const select=node('select',undefined,{'aria-label':'配置 Profile'});for(const name of Object.keys(t.manifest.profiles))select.append(node('option',name,{value:name}));select.value=p;detail.append(select,node('pre',JSON.stringify(toolContext,null,2)),button('保存选择',async()=>{await api('/api/tools/configure',{agent_id:agentId,tool_id:toolId,profile_id:select.value,context:toolContext});profileSelections.set(agentId+':'+toolId,select.value);notice('Profile 选择已保存；运行实例没有被重配。');await poll();}));
 }else if(mode==='logs')detail.append(node('pre',t.instance?.logs?.join('')||'当前没有由 Agent 收集的进程输出。'));
 else {const integration=await api('/api/tools/integration',{agent_id:agentId,tool_id:toolId,profile_id:p});if(detailSelection!==selection)return;detail.append(node('pre',JSON.stringify({integration,external_pids:t.external_pids,integrations:t.manifest.integrations,last_operation:snapshot.tools.jobs.filter(j=>j.agent_id===agentId&&j.tool_id===toolId).at(-1)},null,2)));}
 detail.scrollIntoView({behavior:'smooth',block:'nearest'});
}
function workspaceCall(name,payload){return api('/api/workspaces/'+name,payload).then(async value=>{notice('Workspace '+name+' 请求已记录；准备状态以组件检测结果为准。');await poll();return value;});}
function renderWorkspaces(){
 const manager=snapshot.tools?.workspaces;if(!manager||view!=='workspaces')return;
 const host=$('#workspaces-content');host.className='panel';host.replaceChildren();
 if(manager.fault)host.append(node('p','持久化故障，新的准备操作已被隔离：'+manager.fault));
 if(!manager.definitions.length)host.append(node('p','尚无已保存工作区。从预设开始，选择车辆、Agent 和 Profile，再保存启动。',{class:'muted'}));
 for(const definition of manager.definitions){
  const runs=manager.runs.filter(r=>r.spec.id===definition.id),run=runs.at(-1),row=node('div',undefined,{class:'workspace-row'}),heading=node('div',undefined,{class:'workspace-heading'});
  const title=node('div');title.append(node('strong',definition.name),node('small',` / ${definition.id} · ${definition.context.vehicle_id} · ${definition.context.environment}`));heading.append(title,badge(run?.state||'SAVED',run?.state==='READY'?'good':['FAILED','UNKNOWN'].includes(run?.state)?'error':'warning'));row.append(heading);
  row.append(node('p',definition.components.map(c=>`${c.id} @ ${c.agent_id} / ${c.profile_id}${c.optional?' (可选)':''}`).join(' → '),{class:'muted'}));
  if(run){const completed=run.components.filter(c=>['READY','RUNNING'].includes(c.state)).length,progress=node('div',undefined,{class:'progress'}),bar=node('span');bar.style.width=(100*completed/run.components.length)+'%';progress.append(bar);row.append(progress,node('p',`${completed} / ${run.components.length} 已满足声明条件${run.state==='PREPARED'?' · 部分组件仅确认进程运行，功能/连接仍未确认':''}${run.error?' · '+run.error:''}`,{class:'muted'}));
   for(const c of run.components)row.append(node('p',`${c.id}: ${c.state} · 功能就绪 ${c.observed_ready?'YES':'NO'}${c.instance_id?' · 实例 '+c.instance_id:''}${c.error?' · '+c.error:''}`,{class:'component-state'}));
  }
  const buttons=node('div',undefined,{class:'actions'}),owns=run&&Object.values(manager.leases).some(l=>l.owners.includes(run.id));
  buttons.append(button('Launch Workspace',()=>workspaceCall('launch',{id:definition.id}),!!run&&(!['STOPPED','ABANDONED','FAILED'].includes(run.state)||owns)),button('修改',()=>editWorkspace(structuredClone(definition))));
  if(run){buttons.append(button('Retry Failed',()=>workspaceCall('retry',{run_id:run.id}),run.recovering||!['FAILED','DEGRADED','PREPARED'].includes(run.state)),button('Stop Workspace',()=>workspaceCall('stop',{run_id:run.id}),run.recovering||['STOPPED','ABANDONED'].includes(run.state)));
   if(run.recovering){
    row.append(node('p','后端或 Agent 连接/进程身份变化：实例与所有权需要明确对账。恢复记录不会重启工具；释放记录不代表进程已停止。',{class:'muted'}));
    buttons.append(button('按当前实例恢复记录',async()=>{const instances={};for(const c of run.components){const[a,t]=findTool(c.agent_id,c.tool_id);if(a?.connected&&t?.instance)instances[c.id]=t.instance.instance_id;}await workspaceCall('reconcile',{run_id:run.id,decision:'resume',instances});}),button('释放未确认记录',()=>workspaceCall('reconcile',{run_id:run.id,decision:'release',instances:{}})));
   }
  }
  row.append(buttons);
  if(runs.length){const details=node('details'),summary=node('summary','启动历史 · '+runs.length+' 次');details.append(summary,node('pre',JSON.stringify(runs.map(r=>({id:r.id,state:r.state,started_at:r.started_at,error:r.error})),null,2)));row.append(details);}
  host.append(row);
 }
}
function freshComponent(){
 const choices=[];for(const a of snapshot?.tools?.agents||[])for(const t of a.tools)choices.push([a,t]);const pair=choices.find(([a,t])=>!workspaceDraft?.components.some(c=>c.agent_id===a.id&&c.tool_id===t.manifest.id))||choices[0];
 return {id:'component-'+((workspaceDraft?.components.length||0)+1),agent_id:pair?.[0].id||'select-agent',tool_id:pair?.[1].manifest.id||'select-tool',profile_id:pair?Object.keys(pair[1].manifest.profiles)[0]:'default',depends_on:[],optional:false,wait_for:'ready',timeout_s:120};
}
$('#workspace-new').onclick=guard(()=>{if(!snapshot?.tools?.workspaces)throw Error('请先连接 Tool 服务');editWorkspace({schema:1,id:'workspace-'+crypto.randomUUID().slice(0,8),name:'New Workspace',context:structuredClone(toolContext),components:[freshComponent()]});});
function selectField(values,value,onchange,label){const select=node('select',undefined,{'aria-label':label});for(const[k,text]of values)select.append(node('option',text,{value:k}));if(!values.some(v=>v[0]===value))select.append(node('option',value+' (未注册)',{value}));select.value=value;select.onchange=()=>onchange(select.value);return select;}
function editWorkspace(spec){
 workspaceDraft=spec;const editor=$('#workspace-editor');editor.hidden=false;editor.replaceChildren(node('h2','编辑工作区'));
 const presets=selectField([['blank','选择预设'],...(snapshot.tools.workspaces.templates||[]).map(t=>[t.id,t.name])],'blank',()=>{},'Workspace 预设');
 editor.append(presets,button('载入预设',async()=>{if(presets.value==='blank')return;const value=await api('/api/workspaces/template',{template_id:presets.value,context:toolContext});editWorkspace(value);}));
 const form=node('div',undefined,{class:'form-grid'});for(const[key,label]of [['id','Workspace ID'],['name','名称']]){const l=node('label',label),input=node('input',undefined,{value:spec[key],maxlength:'128'});input.oninput=()=>workspaceDraft[key]=input.value;l.append(input);form.append(l);}editor.append(form,node('pre',JSON.stringify(spec.context,null,2)),button('使用当前 Vehicle Context',()=>{workspaceDraft.context=structuredClone(toolContext);editWorkspace(workspaceDraft);}));
 const table=node('table',undefined,{class:'tools-table workspace-components'}),header=node('tr');for(const title of ['COMPONENT','AGENT / TOOL / PROFILE','DEPENDENCIES','READINESS',''])header.append(node('th',title));const thead=node('thead');thead.append(header);table.append(thead);const body=node('tbody');table.append(body);
 for(const c of spec.components){
  const row=node('tr'),idCell=node('td'),id=node('input',undefined,{value:c.id,'aria-label':'Component ID'});id.oninput=()=>c.id=id.value;idCell.append(id);row.append(idCell);
  const assignment=node('td'),agents=snapshot.tools.agents;
  assignment.append(selectField(agents.map(a=>[a.id,a.id+(a.connected?'':' (离线)')]),c.agent_id,value=>{c.agent_id=value;const a=agents.find(a=>a.id===value);c.tool_id=a?.tools[0]?.manifest.id||'select-tool';c.profile_id=Object.keys(a?.tools[0]?.manifest.profiles||{default:null})[0];editWorkspace(spec);},'组件 Agent'));
  const a=agents.find(a=>a.id===c.agent_id),tools=a?.tools||[];
  assignment.append(selectField(tools.map(t=>[t.manifest.id,t.manifest.name]),c.tool_id,value=>{c.tool_id=value;c.profile_id=Object.keys(tools.find(t=>t.manifest.id===value)?.manifest.profiles||{default:null})[0];editWorkspace(spec);},'组件 Tool'));
  const t=tools.find(t=>t.manifest.id===c.tool_id);assignment.append(selectField(Object.keys(t?.manifest.profiles||{}).map(p=>[p,p]),c.profile_id,value=>c.profile_id=value,'组件 Profile'));row.append(assignment);
  const deps=node('td'),input=node('input',undefined,{value:c.depends_on.join(', '),placeholder:'组件 ID，用逗号分隔','aria-label':'依赖组件'});input.oninput=()=>c.depends_on=input.value.split(',').map(s=>s.trim()).filter(Boolean);deps.append(input);row.append(deps);
  const policy=node('td');policy.append(selectField([['ready','功能就绪'],['running','仅进程运行']],c.wait_for,value=>c.wait_for=value,'组件等待条件'));const optional=node('input',undefined,{type:'checkbox','aria-label':'可选组件'});optional.checked=c.optional;optional.onchange=()=>c.optional=optional.checked;const label=node('label','可选');label.append(optional);policy.append(label);const timeout=node('input',undefined,{type:'number',min:'1',max:'180',value:String(c.timeout_s),'aria-label':'组件超时秒'});timeout.oninput=()=>c.timeout_s=Number(timeout.value);policy.append(timeout);row.append(policy);
  const remove=node('td');remove.append(button('移除',()=>{spec.components=spec.components.filter(x=>x!==c);editWorkspace(spec);}));row.append(remove);body.append(row);
 }
 const wrap=node('div',undefined,{class:'table-wrap'});wrap.append(table);editor.append(wrap,button('添加组件',()=>{spec.components.push(freshComponent());editWorkspace(spec);}),button('保存 Workspace',async()=>{await workspaceCall('save',{spec:workspaceDraft});editor.hidden=true;}),button('关闭编辑',()=>editor.hidden=true));editor.append(node('p','先检查所有必需依赖，再按顺序等待。共享实例保持引用；缺少依赖或无图形环境时不会伪造成功。此操作不触发车辆 Arm 或运动。',{class:'muted'}));
}
function renderLogs(){const filter=$('#log-filter').value.toLowerCase(),lines=(snapshot?.tools?.events||[]).map(e=>JSON.stringify(e));for(const a of snapshot?.tools?.agents||[])for(const t of a.tools)for(const line of t.instance?.logs||[])lines.push(`[${a.id} / ${t.manifest.id}] ${line}`);if(snapshot?.fault)lines.push(snapshot.fault);$('#logs').textContent=lines.filter(s=>s.toLowerCase().includes(filter)).slice(-200).join('\n')||'没有匹配的记录。';}
function fillContext(){const c=toolContext;$('#context-vehicle').value=c.vehicle_id;$('#context-type').value=c.vehicle_type;$('#context-env').value=c.environment;$('#context-namespace').value=c.ros_namespace;$('#context-domain').value=c.ros_domain_id;$('#context-mavlink').value=c.mavlink_profile;}
$('#context-form').onsubmit=guard(async e=>{e.preventDefault();const c={vehicle_id:$('#context-vehicle').value,vehicle_type:$('#context-type').value,environment:$('#context-env').value,ros_namespace:$('#context-namespace').value,ros_domain_id:Number($('#context-domain').value),mavlink_profile:$('#context-mavlink').value};await api('/api/settings/context',c);toolContext=c;notice('上下文已保存。现有工具和车辆任务保持其当前上下文。');});fillContext();
$('#log-filter').oninput=()=>renderLogs();
