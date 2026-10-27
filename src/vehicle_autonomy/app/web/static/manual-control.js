'use strict';
const api=window.VAF,$=s=>document.querySelector(s);
let state=null,parameters={},session=null,input=null,keys=new Set(),pending=false,updating=false,polling=false,mapTransform=null;
const terminal=new Set(['SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN']);
function selected(){return state?.vehicles.find(v=>v.target===api.target);}
function chosen(){return api.catalog.find(s=>s.name+'@'+s.version===$('#action').value);}
function form(){const s=chosen();parameters={};if(s)api.parameters($('#parameters'),s.parameters,parameters);}
const fmt=value=>typeof value==='number'&&Number.isFinite(value)?value.toFixed(2):'未知';
const vector=value=>value?`X ${fmt(value.x)} · Y ${fmt(value.y)} · Z ${fmt(value.z)}`:'未知';
$('#speed').addEventListener('input',()=>{$('#speed-value').textContent=Number($('#speed').value).toFixed(2)+' m/s';});
async function catalog(){await api.loadCatalog();$('#action').replaceChildren();for(const s of api.catalog)$('#action').append(api.node('option',api.actionLabel(s.name)+' · '+api.kindLabel(s.kind),{value:s.name+'@'+s.version}));form();}
$('#connect').onclick=api.guard(async()=>{await api.connect();await catalog();await poll();});
$('#target').onchange=api.guard(async()=>{await stop();await catalog();await poll();});$('#action').onchange=form;
$('#execute').onclick=api.guard(async()=>{
 const s=chosen();if(!s)return;
 if(s.kind==='Continuous'&&s.name!=='Hold')throw Error('持续输入请使用右侧按住操控；Hold 可通过 Action Lab 有界执行。');
 api.validateParameters(s.parameters,parameters);
 const p={name:s.name,version:s.version,target:api.target,parameters,allow_send:$('#send').checked};
 const continuation=$('#continuation').value.trim();if(continuation)p.continuation_of=continuation;
 $('#send').checked=false;const a=await api.call('/api/manual/action',p);$('#log').textContent=JSON.stringify(a,null,2);await poll();
});
$('#reestablish').onclick=api.guard(async()=>{$('#log').textContent=JSON.stringify(await api.call('/api/control/reestablish',{target:api.target}),null,2);await poll();});
$('#takeover').onclick=api.guard(async()=>{$('#log').textContent=JSON.stringify(await api.call('/api/control/takeover',{target:api.target}),null,2);});
function values(){
 const k=selected()?.kind,speed=Number($('#speed').value),axis=(positive,negative)=>(keys.has(positive)?1:0)-(keys.has(negative)?1:0);
 if(k==='rover')return{speed_mps:speed*axis('w','s'),yaw_rate_rad_s:.25*(axis('a','d')||axis('r','f'))};
 return{vx_mps:speed*axis('w','s'),vy_mps:speed*axis('a','d'),vz_mps:.2*axis('q','e'),yaw_rate_rad_s:.25*axis('r','f'),frame:'base_link'};
}
async function begin(){
 if(pending||session||!keys.size)return;
 const v=selected();if(!v||v.kind==='plane')return;
 if(!$('#manual-send').checked){keys.clear();throw Error('请重新授权下一次按住操控');}
 $('#manual-send').checked=false;pending=true;
 try{
  const r=await api.call('/api/manual/start',{name:v.kind==='rover'?'Drive':'SetVelocity',target:api.target,parameters:values(),allow_send:true});
  session=r.session;input=r.action;if(!keys.size)await stop();
 }finally{pending=false;}
}
async function stop(){
 keys.clear();document.querySelectorAll('[data-key]').forEach(b=>b.classList.remove('pressed'));const s=session;session=null;input=null;
 if(s)try{await api.call('/api/manual/stop',{session_id:s.id});}catch(e){api.report('停止请求未确认；服务器 deadman 仍独立生效。'+e.message);}
}
async function update(){
 if(!session||!input||updating||!keys.size)return;
 if(terminal.has(input.state)){session=null;input=null;keys.clear();return;}
 if(input.state!=='RUNNING'){
  try{input=await api.call('/api/manual/state?session_id='+encodeURIComponent(session.id));}catch(e){await stop();api.report(e);return;}
  if(input.state!=='RUNNING')return;
 }
 updating=true;
 try{
  input=await api.call('/api/manual/update',{session_id:session.id,sequence:input.input_sequence+1,deadline_ns:input.input_ticket,parameters:values()});
 }catch(e){await stop();api.report(e);}finally{updating=false;}
}
function down(key){if(!'wasdqerf'.includes(key)||selected()?.kind==='plane')return;keys.add(key);document.querySelector(`[data-key="${key}"]`)?.classList.add('pressed');begin().catch(api.report);}
function up(key){keys.delete(key);if('wasdqerf'.includes(key)&&key.length===1)document.querySelector(`[data-key="${key}"]`)?.classList.remove('pressed');if(!keys.size)stop().catch(api.report);}
for(const b of document.querySelectorAll('[data-key]')){
 b.onpointerdown=e=>{e.preventDefault();b.setPointerCapture(e.pointerId);down(b.dataset.key);};
 b.onpointerup=()=>up(b.dataset.key);b.onpointercancel=()=>stop();
}
window.addEventListener('keydown',e=>{if(['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)||e.repeat)return;if('wasdqerf'.includes(e.key.toLowerCase())){e.preventDefault();down(e.key.toLowerCase());}});
window.addEventListener('keyup',e=>up(e.key.toLowerCase()));window.addEventListener('blur',()=>stop());
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});window.addEventListener('pagehide',()=>stop());$('#manual-stop').onclick=()=>stop();
setInterval(()=>update(),100);
function render(){
 document.querySelectorAll('[data-key]').forEach(b=>b.classList.toggle('pressed',keys.has(b.dataset.key)));
 const v=selected();if(!v)return;
 const w=v.world,vehicle=w?.vehicle,pose=vehicle?.reported_pose,twist=vehicle?.reported_twist;
 $('#stream-controls').hidden=v.kind==='plane';$('#plane-manual-help').hidden=v.kind!=='plane';
 api.connection(v.connected?'车辆已连接 · '+api.kindLabel(v.kind):'车辆连接已中断',v.connected?'connected':'error');
 const grid=$('#status');grid.replaceChildren();
 const metrics={
  '连接状态':v.connected?'已连接':'已断开',
  '签名验证':v.signing_configured?`已验证 ${v.verified_frames} 帧`:'未配置',
  '状态新鲜度':v.fresh_vehicle_state?'有效':'未知',
  '解锁状态':vehicle?.operation?.armed===true?'已解锁':vehicle?.operation?.armed===false?'未解锁':'未知',
  '当前模式':vehicle?.operation?.native_mode??'未知',
  '发送授权':`系统 ${v.system_send?'开':'关'} · 动作 ${v.action_send?'开':'关'}`,
  '车辆执行域':v.scope?'已占用 · 见控制权详情':'无活跃执行域',
  '位置（米）':vector(pose?.value.position),
  'ENU 航向（度）':pose?(Math.atan2(2*(pose.value.orientation.w*pose.value.orientation.z+pose.value.orientation.x*pose.value.orientation.y),1-2*(pose.value.orientation.y**2+pose.value.orientation.z**2))*180/Math.PI).toFixed(1):'未知',
  'odom 向上高度（米）':fmt(pose?.value.position.z),
  '速度（米/秒）':vector(twist?.value.linear),
  '姿态四元数':pose?`W ${fmt(pose.value.orientation.w)} · X ${fmt(pose.value.orientation.x)} · Y ${fmt(pose.value.orientation.y)} · Z ${fmt(pose.value.orientation.z)}`:'未知'};
 for(const[k,value]of Object.entries(metrics)){
  const cell=api.node('div');cell.append(api.node('strong',k),api.node('span',String(value)));
  if(k==='连接状态')cell.dataset.tone=v.connected?'good':'warning';
  if(k==='状态新鲜度')cell.dataset.tone=v.fresh_vehicle_state?'good':'warning';
  grid.append(cell);
 }
 const actions=state.actions.filter(a=>a.target===api.target),missions=state.missions.filter(m=>m.target===api.target);
 if(actions.length)$('#log').textContent=JSON.stringify(actions.at(-1),null,2);
 $('#activity').textContent=JSON.stringify({missions:missions.map(m=>({id:m.id,state:m.state,release_safe:m.release_safe,continuation_of:m.continuation_of})),
  restarted:state.recovered_actions.filter(a=>a.target===api.target),actions:actions.slice(-5).map(a=>({id:a.id,name:a.name,state:a.state,safety:a.safety})),resources:state.resources},null,2);
 const summary=$('#activity-summary');summary.replaceChildren();
 const row=(label,value,warning=false)=>{const el=api.node('div',undefined,{class:'activity-row'}),badge=api.node('span',value);if(warning)badge.dataset.tone='warning';el.append(api.node('strong',label),badge);summary.append(el);};
 row('任务',missions.length?api.stateLabel(missions.at(-1).state):'暂无任务',missions.at(-1)?.state==='UNKNOWN');
 for(const a of actions.slice(-3))row(api.actionLabel(a.name),api.stateLabel(a.state),['UNKNOWN','UNCONFIRMED','FAILED'].includes(a.state));
 row('资源记录',String(state.resources.length)+' 项 · 详见原始记录');
 const uncertain=missions.some(m=>m.state==='UNKNOWN'||!m.release_safe)||actions.some(a=>['UNKNOWN','UNCONFIRMED'].includes(a.state));
 if(uncertain)row('安全退出','含未确认记录，请核查资源',true);
 $('#manual-summary').textContent=session?'输入会话 · '+api.stateLabel(input?.state||'STARTING'):'当前无持续输入会话';
 if(session){const a=actions.find(a=>a.id===session.action_id);if(a&&(!input||a.input_sequence>input.input_sequence||a.input_sequence===input.input_sequence&&(['CANCELLING',...terminal].includes(a.state)||input.state!=='RUNNING')))input=a;
  $('#session').textContent=JSON.stringify({session_id:session.id,action:input?.id,state:input?.state,input_sequence:input?.input_sequence,input_deadline_ns:input?.input_deadline_ns},null,2);
  if(input&&terminal.has(input.state)){session=null;input=null;keys.clear();}}
 const retained=actions.filter(a=>a.state==='SUCCEEDED'&&a.safety?.continuation_allowed).at(-1);
 $('#continuation').placeholder=retained?'续接：'+retained.id:'固定翼续接动作 ID（可选）';
 draw(v);
}
function draw(v){
 const canvas=$('#field'),ctx=canvas.getContext('2d'),W=canvas.width,H=canvas.height;ctx.clearRect(0,0,W,H);ctx.strokeStyle='#244556';
 for(let x=0;x<W;x+=40){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();}for(let y=0;y<H;y+=40){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();}
 const vehicle=v.world?.vehicle,local=vehicle?.reported_pose,global=vehicle?.global_position;
 mapTransform=null;
 if(v.kind==='plane'){
  if(!global){$('#map-frame').textContent='WGS84 位置未知：不能创建地图目标';return;}
  const g=global.value;mapTransform={kind:'plane',x:g.longitude_deg,y:g.latitude_deg,sx:W/.008,sy:H/.004};
  $('#map-frame').textContent=`WGS84 · 经度 ${g.longitude_deg.toFixed(6)}° · 纬度 ${g.latitude_deg.toFixed(6)}° · 海拔 ${g.altitude_m.toFixed(2)}m AMSL · 坐标系 ${global.frame_id}`;
  ctx.strokeStyle='#6fcbc0';ctx.beginPath();let first=true;
  for(const sample of v.track||[]){const g=sample.global_position?.value;if(!g)continue;
   const x=W/2+(g.longitude_deg-mapTransform.x)*mapTransform.sx,y=H/2-(g.latitude_deg-mapTransform.y)*mapTransform.sy;
   if(first){ctx.moveTo(x,y);first=false;}else ctx.lineTo(x,y);
  }ctx.stroke();
  ctx.fillStyle='#87ded6';ctx.beginPath();ctx.arc(W/2,H/2,6,0,Math.PI*2);ctx.fill();
 }else{
  if(!local||local.frame_id!=='odom'){ $('#map-frame').textContent='合格 odom ENU 位置未知';return;}
  const b=v.navigation_bounds||{min_x_m:-16,max_x_m:16,min_y_m:-10,max_y_m:10};
  mapTransform={kind:v.kind,x:(b.min_x_m+b.max_x_m)/2,y:(b.min_y_m+b.max_y_m)/2,sx:W/(b.max_x_m-b.min_x_m),sy:H/(b.max_y_m-b.min_y_m)};
  $('#map-frame').textContent=`odom ENU m · E ${local.value.position.x.toFixed(2)} · N ${local.value.position.y.toFixed(2)} · U ${local.value.position.z.toFixed(2)}`;
  const project=p=>[W/2+(p.x-mapTransform.x)*mapTransform.sx,H/2-(p.y-mapTransform.y)*mapTransform.sy];
  ctx.strokeStyle='#6fcbc0';ctx.lineWidth=2;ctx.beginPath();let first=true;
  for(const s of v.track||[]){if(s.frame!=='odom')continue;const[x,y]=project(s.position);if(first){ctx.moveTo(x,y);first=false;}else ctx.lineTo(x,y);}ctx.stroke();
  const[x,y]=project(local.value.position);ctx.fillStyle='#f1c67c';ctx.beginPath();ctx.arc(x,y,6,0,2*Math.PI);ctx.fill();
 }
}
$('#field').onclick=api.guard(e=>{
 const v=selected();if(!v||!mapTransform||!v.fresh_vehicle_state)throw Error('缺少有效定位；地图目标不可用');
 const box=e.target.getBoundingClientRect(),x=(e.clientX-box.left)*e.target.width/box.width,y=(e.clientY-box.top)*e.target.height/box.height;
 const target={x:mapTransform.x+(x-e.target.width/2)/mapTransform.sx,y:mapTransform.y-(y-e.target.height/2)/mapTransform.sy};
 const name=v.kind==='plane'?'SetGuidedTarget':'Goto',s=api.catalog.find(a=>a.name===name);if(!s)throw Error('车型不支持地图目标');
 $('#action').value=s.name+'@'+s.version;form();
 const values=v.kind==='plane'?{latitude_deg:target.y,longitude_deg:target.x}: {x_m:target.x,y_m:target.y};
 for(const[k,value]of Object.entries(values)){parameters[k]=value;const c=$(`#parameters [name="${k}"]`);if(c)c.value=value;}
 $('#notice').textContent='目标参数已设置，请核对坐标/高度并显式执行。';
});
async function poll(){if(polling)return;polling=true;try{state=await api.call('/api/studio/state');render();}finally{polling=false;}}
setInterval(()=>{if(api.target)poll().catch(api.report);},500);
