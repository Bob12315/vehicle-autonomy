'use strict';
const $=s=>document.querySelector(s),node=(tag,text,attrs={})=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);return e;};
let snapshot=null,connected=false,busy=false,vehicleId='',kindFilter='',view='dashboard',lastReceived=0;
const titles={dashboard:['车辆总览','遥测、执行状态与控制权，来自同一受控运行时。'],tools:['工具管理','选择运行主机，管理外部软件的生命周期与真实连接状态。'],workspaces:['工作环境','按声明的依赖准备工具，保留共享服务的所有权。'],logs:['日志与诊断','追踪工具启动、进程输出、失败和认证操作记录。'],settings:['设置','配置车辆上下文与已注册的工具 Profile。']};
const kindNames={rover:'Rover · 地面车',copter:'Copter · 多旋翼',plane:'Plane · 固定翼'};
let toolContext={vehicle_id:'rover',vehicle_type:'rover',environment:'simulation',ros_namespace:'/rover',ros_domain_id:91,mavlink_profile:'monitor'};
const num=(v,d=2)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(d):'未知';
const vector=v=>v?`X ${num(v.x)} / Y ${num(v.y)} / Z ${num(v.z)}`:'未知';
const badge=(text,tone='')=>node('span',text,{class:'badge','data-tone':tone});
function notice(e){$('#notice').textContent=e?.message||String(e||'');}
function guard(fn){return async(...args)=>{try{await fn(...args);}catch(e){notice(e);}};}
async function api(path,payload){
 const token=$('#token').value.trim();if(!token)throw Error('请先输入访问令牌');
 const headers={Authorization:'Bearer '+token},options={headers,signal:AbortSignal.timeout(3500)};
 if(payload!==undefined){Object.assign(headers,{'Content-Type':'application/json','X-VAF-CSRF':token,'X-VAF-Request-ID':crypto.randomUUID()});Object.assign(options,{method:'POST',body:JSON.stringify(payload)});}
 const r=await fetch(path,options),data=await r.json();if(!r.ok||!data.ok)throw Error(data.error||'请求失败');return data.result;
}
function route(){view=location.hash.slice(1)||'dashboard';if(!titles[view])view='dashboard';for(const e of document.querySelectorAll('[data-panel]'))e.hidden=e.dataset.panel!==view;for(const e of document.querySelectorAll('[data-view]')){if(e.dataset.view===view)e.setAttribute('aria-current','page');else e.removeAttribute('aria-current');}$('#page-title').textContent=titles[view][0];$('#page-subtitle').textContent=titles[view][1];if(snapshot)render();}
window.addEventListener('hashchange',route);route();
function linkState(ok){$('#link-state').textContent=ok?'控制中心已连接':'控制中心已断开 · 状态未知';$('#link-dot').style.background=ok?'#087e79':'#ad3c32';}
function invalidate(){if(!snapshot)return;snapshot.vehicles=[];$('#dashboard-data').hidden=true;$('#vehicle-empty').hidden=false;$('#vehicle-empty').replaceChildren(node('strong','连接中断，当前状态未知'),node('p','连接恢复后同步完整状态。已显示的旧遥测不能用于操作。'));linkState(false);}
async function poll(){if(busy||!connected)return;busy=true;try{snapshot=await api('/api/console/state');lastReceived=performance.now();linkState(true);$('#updated').textContent='已同步 '+new Date().toLocaleTimeString();render();}catch(e){invalidate();notice(e);}finally{busy=false;}}
$('#connection').onsubmit=guard(async e=>{e.preventDefault();connected=true;notice('');await poll();});
$('#disconnect').onclick=()=>{connected=false;invalidate();$('#token').value='';};
setInterval(()=>{if(connected)poll();if(lastReceived&&performance.now()-lastReceived>4500)invalidate();},750);
$('#vehicle').onchange=()=>{vehicleId=$('#vehicle').value;const v=snapshot?.vehicles.find(v=>v.id===vehicleId);if(v){toolContext={...toolContext,vehicle_id:v.id,vehicle_type:v.type,environment:v.environment==='simulation'?'simulation':'hardware_readonly',ros_namespace:'/'+v.id.replace(/[^A-Za-z0-9_]/g,'_')};fillContext();}render();};
for(const b of document.querySelectorAll('[data-kind]'))b.onclick=()=>{kindFilter=b.dataset.kind;for(const x of document.querySelectorAll('[data-kind]'))x.setAttribute('aria-pressed',String(x===b));render();};
function list(target,items){target.replaceChildren();for(const[k,v]of items){const row=node('div');row.append(node('dt',k),node('dd',v??'未知'));target.append(row);}}
function render(){
 const available=snapshot.vehicles.filter(v=>!kindFilter||v.type===kindFilter),select=$('#vehicle');
 if(!available.some(v=>v.id===vehicleId))vehicleId=available[0]?.id||'';
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
 renderTools();renderWorkspaces();renderLogs();$('#settings-info').textContent=JSON.stringify({agents:snapshot.tools?.agents?.map(a=>({id:a.id,role:a.role,connected:a.connected})),poll_interval_ms:750,transport:'Authenticated HTTP / SSH forwarding',vehicle_command_path:'Existing MissionControl / ActionRuntime / Execution'},null,2);
}
function renderTools(){if(snapshot.tools)$('#tools-content').textContent='等待工具状态同步。';}
function renderWorkspaces(){}
function renderLogs(){$('#logs').textContent=JSON.stringify(snapshot?.tools?.events||{vehicle_fault:snapshot?.fault||null},null,2);}
function fillContext(){const c=toolContext;$('#context-vehicle').value=c.vehicle_id;$('#context-type').value=c.vehicle_type;$('#context-env').value=c.environment;$('#context-namespace').value=c.ros_namespace;$('#context-domain').value=c.ros_domain_id;$('#context-mavlink').value=c.mavlink_profile;}
$('#context-form').onsubmit=guard(async e=>{e.preventDefault();const c={vehicle_id:$('#context-vehicle').value,vehicle_type:$('#context-type').value,environment:$('#context-env').value,ros_namespace:$('#context-namespace').value,ros_domain_id:Number($('#context-domain').value),mavlink_profile:$('#context-mavlink').value};await api('/api/settings/context',c);toolContext=c;notice('上下文已保存。现有工具和车辆任务保持其当前上下文。');});fillContext();
$('#log-filter').oninput=()=>renderLogs();
