'use strict';
const api=window.VAF,auth=window.VAFAuth,$=s=>document.querySelector(s);
const terminal=new Set(['SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN']);
let state=null,current=null,controller=null,session=null,input=null,keys=new Set(),pending=false,updating=false,polling=false,renewing=false,commandPending=false,confirmation=null,socket=null,retry=0,closing=false,lastAction=null,targetHeight=null,lastReceived=0;
let sendChanging=false;
let velocityEnabled=false,velocityUntil=0,motionGeneration=0;
let lastInputReplyAt=0;
const node=api.node.bind(api),fmt=(v,n=2)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(n):'未知';
function notice(error){$('#notice').textContent=String(error?.message||error||'');$('#notice').dataset.tone=error?.message?'error':'info';}
function guard(fn){return async(...args)=>{try{await fn(...args);}catch(e){notice(e);}};}
function selected(){return state?.vehicles.find(v=>v.target===api.target);}
function activeAction(){return state?.actions.find(a=>a.target===api.target&&a.kind!=='Query'&&!terminal.has(a.state));}
function spec(name){return api.catalog.find(a=>a.name===name);}
function control(){return state?.operator_control?.[api.target];}
function manual(){return !!(auth.control&&control()?.mine&&control()?.state==='MANUAL_CONTROL');}
function canCommand(){return manual()&&selected()?.fresh_vehicle_state&&!activeAction()&&!commandPending;}
function list(target,rows){target.replaceChildren();for(const[k,v]of rows){const row=node('div');row.append(node('dt',k),node('dd',v??'未知'));target.append(row);}}
function diagnostic(display,type,fn){const field=display?.diagnostics?.[type];if(!field?.value)return'未知';if(!field.receive_fresh||field.availability==='STALE')return'过期 / 未知';return fn(field.value)+(field.availability==='UNKNOWN_CAPTURE_TIME'?' · 采样时间未知':'');}
function actionStatus(a){return a.state==='CANCELLED'&&a.safety?.release_safe&&['Drive','SetVelocity'].includes(a.name)?'已停止输入':api.stateLabel(a.state);}
function merge(value,withControl=false){
 if(state?.observed_at_ns&&BigInt(value.observed_at_ns)<BigInt(state.observed_at_ns)){if(withControl)state.operator_control=value.operator_control;return;}
 state={...value,operator_control:withControl?value.operator_control:state?.operator_control||{}};lastReceived=performance.now();render();
}
async function refresh(){if(polling||closing)return;polling=true;try{merge(await api.call('/api/control/state'),true);}catch(e){invalidate();throw e;}finally{polling=false;}}
function invalidate(){if(state)for(const v of state.vehicles){v.fresh_vehicle_state=false;v.connected=false;}render();}
async function loseControl(message){
 const token=auth.control;
 await stop();
 if(token&&api.target)try{await api.call('/api/control/release',{target:api.target});}catch(_){}
 auth.control='';if(state?.operator_control?.[api.target])state.operator_control[api.target].mine=false;
 if(message)notice(message);render();
}
async function renew(){
 if(!auth.control||renewing||closing)return;renewing=true;
 try{await api.call('/api/control/renew',{target:api.target});}
 catch(e){await loseControl('SEND 已关闭：'+e.message);}
 finally{renewing=false;}
}
function live(){
 if(closing)return;
 socket=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/ws/telemetry');
 socket.onopen=()=>{$('#live-status').textContent='LIVE · WebSocket';retry=0;};
 socket.onmessage=e=>{try{const m=JSON.parse(e.data);if(m.type==='telemetry')merge(m.result);}catch(_){notice('状态帧无效；已暂停操作。');invalidate();loseControl();}};
 socket.onclose=e=>{
  if(closing)return;$('#live-status').textContent='重连中 · HTTP 回退';invalidate();loseControl('实时连接中断，SEND 已关闭；重连后请重新点击 SEND ON。');
  if(e.code===4401){auth.lost();return;}setTimeout(live,Math.min(5000,700*2**retry++));
 };
 socket.onerror=()=>{};
}
function confirmOperation(title,description,fn){
 if(confirmation)throw Error('请先处理当前确认操作');
 confirmation=fn;$('#confirm-title').textContent=title;$('#confirm-description').textContent=description;$('#confirm-submit').disabled=false;$('#command-confirm').showModal();
}
$('#confirm-cancel').onclick=()=>{$('#command-confirm').close();confirmation=null;};
$('#command-confirm').addEventListener('cancel',()=>confirmation=null);
$('#confirm-submit').onclick=guard(async()=>{
 if(!confirmation)return;
 const fn=confirmation;confirmation=null;$('#command-confirm').close();await fn();
});
function request(name,parameters={}){
 if(!canCommand())throw Error('请先点击 SEND ON，等待有效遥测及当前动作退出');
 if(!spec(name))throw Error('当前车型未注册此能力');
 const submit=async()=>{
  if(!canCommand())throw Error('控制状态已变化，请重新核查');
  commandPending=true;render();
  try{
   const payload={name,version:spec(name).version,target:api.target,parameters,allow_send:true};
   const retained=state.actions.filter(a=>a.target===api.target&&a.state==='SUCCEEDED'&&a.safety?.continuation_allowed).at(-1);
   if(selected().kind==='plane'&&retained)payload.continuation_of=retained.id;
   const a=await api.call('/api/manual/action',payload);lastAction=a.id;
   if(name==='Takeoff')targetHeight=parameters.height_m;
   notice('已受理 '+api.actionLabel(name)+'；等待独立的飞控与状态确认。');
   await refresh();
  }finally{commandPending=false;render();}
 };
 return submit();
}
$('#acquire-control').onclick=guard(async()=>{
 if(sendChanging)return;
 if(!selected())throw Error('无车辆可开启 SEND');
 sendChanging=true;
 $('#control-level').textContent='SEND · 开启中';$('#acquire-control').disabled=true;
 try{const r=await api.call('/api/control/acquire',{target:api.target});auth.control=r.control_token;notice('SEND ON：本页本车已启用，后续按钮直接执行，不再逐条授权。');await refresh();}
 finally{sendChanging=false;render();}
});
$('#release-control').onclick=guard(async()=>{await loseControl('已请求安全退出；确认释放状态以右侧证据为准。');await refresh();});
$('#request-takeover').onclick=guard(()=>{
 confirmOperation('退出当前任务',`目标 ${api.target}\n先请求当前 Mission / Action 安全退出。未确认退出时仍禁止新运动。`,async()=>{await api.call('/api/control/request-takeover',{target:api.target,confirmed:true});await loseControl();await refresh();notice('退出请求已提交；等待原主体释放后，再点击 SEND ON。');});
});
$('#safety-entry').onclick=guard(async()=>{if(auth.control){await loseControl('安全退出已请求；不将取消等同于物理停止。');await refresh();}else $('#request-takeover').click();});
$('#set-mode').onclick=guard(()=>request('SetMode',{mode:$('#mode').value}));
for(const b of document.querySelectorAll('[data-action]'))b.onclick=guard(()=>request(b.dataset.action));
$('#takeoff').onclick=guard(()=>{const height=Number($('#takeoff-height').value);if(!Number.isFinite(height)||height<.2||height>2)throw Error('起飞高度须为 0.2–2 m');return request('Takeoff',{height_m:height});});
$('#plane-takeoff').onclick=guard(()=>request('Takeoff',{height_m:Number($('#plane-height').value)}));
$('#return-control').onclick=guard(()=>request(selected()?.kind==='plane'?'RTL':'ReturnHome'));
$('#hold-control').onclick=guard(async()=>{
 if(session){if(velocityEnabled){neutral();return;}await stop();return;}
 if(!canCommand())throw Error('请先开启 SEND ON 并等待有效遥测');
 if(selected().kind==='rover')return request('Stop');
 if(selected().kind==='copter')return request('SetMode',{mode:'LOITER'});
 return request('Loiter');
});
$('#guided-target').onclick=guard(()=>{
 const parameters={latitude_deg:Number($('#latitude').value),longitude_deg:Number($('#longitude').value),altitude_amsl_m:Number($('#altitude-amsl').value)};
 if(['#latitude','#longitude','#altitude-amsl'].some(id=>$(id).value.trim()==='')||Object.values(parameters).some(v=>!Number.isFinite(v)))throw Error('请填写完整的 WGS84 经纬度与 AMSL 目标海拔');
 return request('SetGuidedTarget',parameters);
});
$('#goto').onclick=guard(()=>{
 const fields=selected().kind==='rover'?['#goto-x','#goto-y']:['#goto-x','#goto-y','#goto-z'];
 if(fields.some(id=>$(id).value.trim()===''||!Number.isFinite(Number($(id).value))))throw Error('请填写完整的有限位置坐标');
 return request('Goto',{x_m:Number($('#goto-x').value),y_m:Number($('#goto-y').value),z_m:selected().kind==='rover'?0:Number($('#goto-z').value)});
});
// Copter's existing velocity interface is deliberately behind the advanced panel.
const stream=$('#copter-stream');
const motionSwitch=node('button','引导速度控制 OFF · 开启',{id:'copter-motion-toggle',class:'primary','aria-pressed':'false'});
const motionStatus=node('p','开启后按住运动，松开按键或点击保持即可归零；关闭才退出。单次上限 60 秒。',{id:'copter-motion-state',class:'muted small-note',role:'status'});
stream.append(motionSwitch,motionStatus);
motionSwitch.onclick=guard(async()=>{
 if(velocityEnabled){await stop();notice('已关闭引导速度控制，等待实际安全退出。');return;}
 if(!canCommand()||selected()?.kind!=='copter')throw Error('请在多旋翼页面开启 SEND ON 并等待当前动作退出');
 velocityEnabled=true;velocityUntil=performance.now()+60000;
 try{await begin();}catch(e){velocityEnabled=false;throw e;}finally{render();}
});
stream.append(node('div',undefined,{class:'speed-row'}));stream.lastChild.append(node('label','速度限制',{for:'copter-speed'}),node('input',undefined,{id:'copter-speed',type:'range',min:'.1',max:'.5',step:'.05',value:'.3'}),node('output','0.30 m/s',{id:'copter-speed-value'}));
const pad=node('div',undefined,{class:'direction-pad'});
for(const[key,label,position]of [['w','↑ 前进','forward'],['a','← 左移','left'],['d','→ 右移','right'],['s','↓ 后退','back']]){const b=node('button',label,{'data-key':key,'data-needs-control':'',class:'key-'+position});pad.append(b);}
const cstop=node('button','HOLD',{class:'key-stop danger',id:'copter-manual-stop','data-needs-control':''});pad.append(cstop);stream.append(pad);
const extra=node('div',undefined,{class:'extra-keys'});for(const[key,label]of [['q','Q · 上升'],['e','E · 下降'],['r','R · 左转向'],['f','F · 右转向']])extra.append(node('button',label,{'data-key':key,'data-needs-control':''}));stream.append(extra);
for(const prefix of ['', 'copter-'])$('#'+prefix+'speed').oninput=()=>$('#'+prefix+'speed-value').textContent=Number($('#'+prefix+'speed').value).toFixed(2)+' m/s';
function streamPrefix(){return selected()?.kind==='copter'?'copter-':'';}
function values(){
 const speed=Number($('#'+streamPrefix()+'speed').value),axis=(p,n)=>(keys.has(p)?1:0)-(keys.has(n)?1:0);
 if(selected()?.kind==='rover')return{speed_mps:speed*axis('w','s'),yaw_rate_rad_s:.25*(axis('a','d')||axis('r','f'))};
 return{vx_mps:speed*axis('w','s'),vy_mps:speed*axis('a','d'),vz_mps:.2*axis('q','e'),yaw_rate_rad_s:.25*axis('r','f'),frame:'base_link'};
}
async function begin(){
 if(pending||session||(!keys.size&&!velocityEnabled))return;
 if(!canCommand()||selected().kind==='plane'){keys.clear();throw Error('持续控制不可用');}
 const v=selected(),op=v.world?.vehicle?.operation,height=v.world?.vehicle?.reported_pose?.value.position.z;
 if(op?.armed!==true||op.native_mode!=='ARDUPILOT_CUSTOM_'+(v.kind==='rover'?15:4)||v.kind==='copter'&&!(height>.3)){keys.clear();throw Error('请先切换 GUIDED、解锁；多旋翼必须先起飞。');}
 pending=true;
 const generation=motionGeneration,target=api.target;
 try{
  const payload={name:v.kind==='rover'?'Drive':'SetVelocity',target,parameters:values(),allow_send:true};
  if(velocityEnabled)payload.timeout_s=60;
  const r=await api.call('/api/manual/start',payload);
  if(generation!==motionGeneration||target!==api.target||!manual()){
   try{await api.call('/api/manual/stop',{session_id:r.session.id});}catch(_){}
   return;
  }
  session=r.session;input=r.action;lastAction=input.id;lastInputReplyAt=0;
  if(!keys.size&&!velocityEnabled)await stop();
 }finally{pending=false;render();}
}
function clearKeys(){keys.clear();for(const b of document.querySelectorAll('[data-key]'))b.classList.remove('pressed');}
function neutral(){clearKeys();if(velocityEnabled&&session)update();render();}
async function stop(){motionGeneration++;velocityEnabled=false;velocityUntil=0;clearKeys();const s=session;session=null;input=null;render();if(s)try{await api.call('/api/manual/stop',{session_id:s.id});}catch(e){notice('停止请求未确认；独立 watchdog 仍生效。'+e.message);}}
async function update(){
 if(!session||!input||updating||(!keys.size&&!velocityEnabled))return;
 // Key changes may arrive just after a heartbeat. Preserve the server's
 // 20 Hz input limit instead of turning a rapid release into an exit error.
 if(performance.now()-lastInputReplyAt<60)return;
 if(!manual()||!selected()?.fresh_vehicle_state){await stop();return;}
 updating=true;
 const currentSession=session;
 try{
  if(terminal.has(input.state)){velocityEnabled=false;session=null;input=null;clearKeys();render();return;}
  let next=input;
  if(next.state!=='RUNNING')next=await api.call('/api/manual/state?session_id='+encodeURIComponent(currentSession.id));
  if(session?.id!==currentSession.id)return;
  if(next.state==='RUNNING'){
   next=await api.call('/api/manual/update',{session_id:currentSession.id,sequence:next.input_sequence+1,deadline_ns:next.input_ticket,parameters:values()});
   if(session?.id===currentSession.id)lastInputReplyAt=performance.now();
  }
  if(session?.id===currentSession.id)input=next;
 }catch(e){if(session?.id===currentSession.id){await stop();notice(e);}}finally{updating=false;}
}
function down(key){if(!'wasdqerf'.includes(key)||!manual()||selected()?.kind==='plane'||selected()?.kind==='copter'&&!velocityEnabled)return;keys.add(key);for(const b of document.querySelectorAll('[data-key]'))b.classList.toggle('pressed',keys.has(b.dataset.key));if(session)update();else begin().catch(notice);}
function up(key){keys.delete(key);for(const b of document.querySelectorAll('[data-key]'))b.classList.toggle('pressed',keys.has(b.dataset.key));if(!keys.size){if(velocityEnabled)neutral();else stop();}else if(session)update();}
for(const b of document.querySelectorAll('[data-key]')){b.onpointerdown=e=>{e.preventDefault();b.setPointerCapture(e.pointerId);down(b.dataset.key);};b.onpointerup=()=>up(b.dataset.key);b.onpointercancel=()=>{if(velocityEnabled)neutral();else stop();};}
window.addEventListener('keydown',e=>{if(e.repeat||e.target.matches('textarea,select,input:not([type="checkbox"]):not([type="range"])')||e.target.isContentEditable||$('#command-confirm').open)return;if('wasdqerf'.includes(e.key.toLowerCase())){e.preventDefault();down(e.key.toLowerCase());}});
window.addEventListener('keyup',e=>up(e.key.toLowerCase()));window.addEventListener('blur',()=>stop());
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
window.addEventListener('pagehide',()=>{closing=true;stop();if(auth.control)loseControl();if(socket)socket.close();});
window.addEventListener('vaf:auth-lost',()=>{closing=true;stop();auth.control='';if(socket)socket.close();});
$('#manual-stop').onclick=()=>stop();$('#copter-manual-stop').onclick=()=>{if(velocityEnabled)neutral();else stop();};
function renderFeedback(){
 const actions=state.actions.filter(a=>a.target===api.target),a=actions.find(a=>a.id===lastAction)||actions.at(-1);
 $('#recent-commands').replaceChildren();for(const old of actions.slice(-5).reverse()){const row=node('div');row.append(node('span',api.actionLabel(old.name)),node('span',actionStatus(old),{class:'badge','data-tone':old.state==='SUCCEEDED'||old.safety?.release_safe?'good':'warning'}));$('#recent-commands').append(row);}
 if(!a)return;
 $('#current-command').textContent=api.actionLabel(a.name);$('#command-state').textContent=actionStatus(a);
 $('#stage-request').textContent='已受理 · '+a.id.slice(-8);
 const evidence=a.command_evidence||[],phases=evidence.map(e=>e.phase),acks=evidence.filter(e=>e.ack_evidence);
 $('#stage-send').textContent=phases.some(p=>['TRANSMITTED','ACKNOWLEDGED','COMPLETED'].includes(p))?'已写入 / 发送':phases.includes('UNKNOWN')?'发送结果未确认':a.state==='REJECTED'?'被拒绝，未放行':'等待执行 / 尚无证据';
 $('#stage-ack').textContent=acks.length?'收到飞控应答 · 结果码 '+acks.at(-1).ack_evidence.result+'（仍须核对目标状态）':evidence.some(e=>e.effect_type==='TwistTargetEffect'||e.effect_type==='PoseTargetEffect')?'此类目标指令不提供 MAVLink 应答':'未收到 / 未提供';
 $('#stage-state').textContent=phases.includes('COMPLETED')?(a.name==='SetGuidedTarget'?'目标配置已确认，非到达':a.name==='SetMode'||a.name==='Loiter'||a.name==='RTL'?'飞控配置已确认，非物理到达':'已有命令状态确认'):'等待实际状态确认';
 if(a.result?.physical_goal_observed)$('#stage-state').textContent='实际目标已观察并确认';
 if(['UNKNOWN','TIMED_OUT','FAILED'].includes(a.state)&&!a.safety?.release_safe)$('#stage-state').textContent='结果 / 安全退出未确认';
 const failure=a.error||a.safety?.reason||'';$('#command-error').textContent=failure?VAFI18n.error(failure):'';$('#command-error').title=failure?'原始诊断：'+failure:'';$('#command-error').dataset.tone=a.error?'error':'';
}
function render(){
 const v=selected();if(!v)return;
 if(session){const a=state.actions.find(a=>a.id===session.action_id);if(a&&terminal.has(a.state)){velocityEnabled=false;session=null;input=null;clearKeys();}}
 const fresh=v.fresh_vehicle_state,veh=fresh?v.world?.vehicle:null,display=fresh?v.display||{}:{},pose=veh?.reported_pose?.value,op=veh?.operation,ctrl=control(),mine=manual();
 $('#vehicle-name').textContent=v.target+' / '+api.kindLabel(v.kind);$('#kind-label').textContent=api.kindLabel(v.kind);
 $('#environment').textContent=v.owned_simulation?'SITL · 自有仿真':'真实硬件 / 未准入 · 只读';$('#connection-state').textContent=v.connected?'MAVLink · 已连接':'MAVLink · 已断开';$('#link-dot').style.background=fresh?'#087e79':'#9a661b';
 $('#top-mode').textContent='Mode · '+(display.mode_name||'未知');$('#top-armed').textContent=op?.armed===true?'ARMED':op?.armed===false?'DISARMED':'Armed · 未知';$('#top-armed').dataset.tone=op?.armed===true?'warning':'';
 $('#top-authority').textContent=mine?'SEND ON':ctrl?.state==='RELEASING'?'Stopping':'SEND OFF';$('#control-level').textContent=mine?'SEND ON · 指令可发送':ctrl?.state==='RELEASING'?'SEND OFF · 安全退出中':'SEND OFF · 只读观察';$('#control-badge').textContent=mine?'SEND ON':'SEND OFF';
 $('#control-reason').textContent=ctrl?.reason||'开启一次指令发送后，按钮直接执行；关闭、断线、刷新或切换车辆后需重新开启。';$('#acquire-control').disabled=sendChanging||!ctrl?.can_acquire;$('#acquire-control').hidden=mine;$('#release-control').hidden=!mine;
 $('#request-takeover').hidden=mine||!ctrl?.holder;
 $('#status-health').textContent=fresh?veh?.health?.quality||'UNKNOWN':'STALE / UNKNOWN';$('#status-health').dataset.tone=fresh?'good':'warning';
 let heading=typeof display.heading_enu_deg==='number'?(90-display.heading_enu_deg+360)%360:null;
 const rows=[['Vehicle ID / Type',v.target+' / '+api.kindLabel(v.kind)],['Flight Mode',display.mode_name||'未知'],['Armed',op?.armed===true?'已解锁':op?.armed===false?'Disarmed':'未知'],['Battery',display.battery?.remaining_percent==null?'未知':fmt(display.battery.remaining_percent,0)+' %'],['Voltage',display.battery?.voltage_v==null?'未知':fmt(display.battery.voltage_v)+' V'],['Ground Speed',fmt(display.horizontal_speed_mps)+' m/s'],['Altitude · odom U',fmt(pose?.position.z)+' m'],['Heading · N / CW',fmt(heading,1)+'°'],['GPS Fix / Satellites',diagnostic(display,'GPS_RAW_INT',g=>'Fix '+g.fix_type+' / '+(g.satellites??'未知'))],['EKF',diagnostic(display,'EKF_STATUS_REPORT',e=>'Flags '+e.flags)],['Failsafe',typeof display.failsafe==='boolean'?(display.failsafe?'触发':'未触发'):'未知 · 未提供独立标志'],['Telemetry',fresh?'有效 · '+fmt(display.pose_age_s,2)+' s':'过期 / 未知']];
 if(v.kind==='plane'){rows.splice(7,0,['Airspeed',fmt(display.airspeed_mps)+' m/s']);rows.push(['Relative Altitude',fmt(pose?.position.z)+' m'],['AMSL',fmt(veh?.global_position?.value.altitude_m)+' m']);}
 list($('#vehicle-status'),rows);
 const q=pose?.orientation;
 $('#roll').textContent=q?fmt(Math.atan2(2*(q.w*q.x+q.y*q.z),1-2*(q.x*q.x+q.y*q.y))*180/Math.PI,1)+'°':'未知';$('#pitch').textContent=q?fmt(Math.asin(Math.max(-1,Math.min(1,2*(q.w*q.y-q.z*q.x))))*180/Math.PI,1)+'°':'未知';$('#yaw').textContent=fmt(display.heading_enu_deg,1)+'°';
 $('#telemetry-warning').textContent=fresh?'已验证 '+v.verified_frames+' 帧 · 定位基于真实遥测':'遥测过期或未知，危险操作已禁用。';$('#telemetry-warning').dataset.tone=fresh?'':'warning';
 $('#control-hint').textContent=(display.control_hint||'等待有效遥测。').replaceAll('再授权','再');$('#actual-height').textContent=fmt(pose?.position.z)+' m';$('#target-height').textContent=targetHeight==null?'尚未提交':fmt(targetHeight)+' m';
 for(const section of document.querySelectorAll('[data-for]'))section.hidden=section.dataset.for!==v.kind;
 $('#position-advanced').hidden=v.kind==='plane';$('#goto-z').disabled=v.kind==='rover';if(v.kind==='rover')$('#goto-z').value='0';
 const choices=display.mode_choices||[],mode=$('#mode'),prior=mode.value;
 if(JSON.stringify([...mode.options].map(o=>o.value))!==JSON.stringify(choices)){mode.replaceChildren(...choices.map(m=>node('option',m,{value:m})));if(choices.includes(prior))mode.value=prior;}
 const enabled=canCommand();for(const b of document.querySelectorAll('[data-needs-control]'))b.disabled=!enabled;
 mode.disabled=!enabled||!choices.length;
 for(const b of document.querySelectorAll('[data-action]')){b.disabled=!enabled||!spec(b.dataset.action);if(b.dataset.action==='Arm')b.disabled=b.disabled||op?.armed!==false;if(b.dataset.action==='Disarm')b.disabled=b.disabled||!op?.armed||!(Math.abs(pose?.position.z??Infinity)<.3);}
 for(const b of document.querySelectorAll('[data-action="Loiter"],[data-action="RTL"]'))b.disabled=b.disabled||!op?.armed||v.kind==='plane'&&!(pose?.position.z>=10);
 $('#set-mode').disabled=!enabled||!choices.length;$('#takeoff').disabled=!enabled||op?.armed!==true||op.native_mode!=='ARDUPILOT_CUSTOM_4'||!(pose?.position.z<.3);$('#plane-takeoff').disabled=!enabled||op?.armed!==true||!(pose?.position.z<.3);
 $('#return-control').disabled=!enabled||!spec(v.kind==='plane'?'RTL':'ReturnHome')||!op?.armed;$('#hold-control').disabled=!mine||!fresh||(!session&&!enabled)||!op?.armed;
 $('#hold-control').querySelector('strong').textContent=({rover:'停车 / HOLD',copter:'Hold / LOITER',plane:'LOITER · 盘旋'})[v.kind];$('#return-control').querySelector('small').textContent=v.kind==='plane'?'原生 RTL · 非着陆':'RETURN HOME';
 $('#guided-target').disabled=!enabled||!spec('SetGuidedTarget')||!op?.armed||!(pose?.position.z>=10);$('#goto').disabled=!enabled||!spec('Goto')||!op?.armed;
 for(const b of document.querySelectorAll('[data-key]')){const movingAllowed=mine&&fresh&&op?.armed===true&&op.native_mode==='ARDUPILOT_CUSTOM_'+(v.kind==='rover'?15:4)&&(v.kind==='rover'||velocityEnabled&&pose?.position.z>.3)&&(!activeAction()||!!session);b.disabled=!movingAllowed;b.classList.toggle('pressed',keys.has(b.dataset.key));}
 $('#manual-stop').disabled=!mine;$('#copter-manual-stop').disabled=!mine;
 motionSwitch.textContent=velocityEnabled?'引导速度控制 ON · 点击关闭':'引导速度控制 OFF · 点击开启';motionSwitch.setAttribute('aria-pressed',String(velocityEnabled));
 motionSwitch.disabled=pending||!mine||!fresh||(!velocityEnabled&&(!enabled||v.kind!=='copter'||op?.armed!==true||op.native_mode!=='ARDUPILOT_CUSTOM_4'||!(pose?.position.z>.3)));
 motionStatus.textContent=velocityEnabled?(pending?'正在建立零速度控制会话…':(keys.size?'目标速度输入中':'零速度保持 · 会话继续')+' · 剩余约 '+Math.max(0,Math.ceil((velocityUntil-performance.now())/1000))+' 秒。松开 / 保持 不退出；关闭后可切模式或降落。'):'开启后按住运动，松开按键或点击保持即可归零；关闭才退出。单次上限 60 秒，失焦/断线仍安全退出。';
 if(velocityEnabled){$('#hold-control').querySelector('strong').textContent='归零保持';$('#control-hint').textContent='引导速度控制已开启；松开归零，关闭开关并确认退出后可切模式/降落。';}
 list($('#authority-info'),[['控制者',ctrl?.holder||'无'],['本页 SEND',mine?'ON':'OFF'],['当前指令系统 SEND',v.system_send?'ON':'OFF'],['当前 Action SEND',v.action_send?'ON':'OFF'],['Execution Lease',v.lease_active?'ACTIVE':'无'],['Scope',v.scope||'无']]);
 $('#preflight').replaceChildren();const labels={telemetry_valid:'有效遥测',owned_simulation:'明确自有仿真',deployment_send:'部署发送授权',runtime_healthy:'Runtime 无故障',physical_scope_free:'执行域可用'};
 for(const[k,label]of Object.entries(labels)){const row=node('div'),ok=ctrl?.preflight?.[k]===true;row.append(node('span',label),node('span',ok?'已满足':'未满足 / 未知',{class:'check-state','data-ok':String(ok)}));$('#preflight').append(row);}
 $('#safety-badge').textContent=fresh?'以动作准入检查为准':'BLOCKED';$('#safety-badge').dataset.tone=fresh?'':'warning';
 const goal=state.actions.filter(a=>a.target===api.target&&a.name==='SetGuidedTarget').at(-1);if(goal)$('#navigation-target').textContent=`请求目标：${goal.parameters.latitude_deg}°, ${goal.parameters.longitude_deg}° / ${goal.parameters.altitude_amsl_m} m AMSL · ${actionStatus(goal)}`;
 renderFeedback();renderTools();renderGoals();window.VAFVisualization.render($('#visualization-entry'),state,api.target);$('#diagnostics').textContent=JSON.stringify({vehicle:v,control:ctrl,last_action:state.actions.find(a=>a.id===lastAction),resources:state.resources},null,2);
}
function renderGoals(){
 const root=$('#pending-goals'),goals=state.visualization_goals?.[api.target]||[];root.replaceChildren();
 if(!goals.length){root.append(node('p','RViz 点选只创建候选；不会直接发送 Nav2 或车辆命令。',{class:'muted small-note'}));return;}
 for(const goal of goals.slice(-3).reverse()){
  const row=node('div',undefined,{class:'tool-shortcut','data-goal':goal.id}),text=node('div');
  text.append(node('strong',goal.position.map(v=>fmt(v)).join(' / ')+' m · '+goal.frame),node('small',goal.action_id?'已提交 '+goal.action_id:goal.reason||'剩余 '+Math.floor(goal.remaining_s)+' s · 尚未执行'),node('small','现有 Goto 只执行 odom ENU 位置；选定朝向仅预览。'));row.append(text);
  const button=node('button','执行此目标');button.disabled=!goal.executable||!!goal.action_id||!canCommand();
  button.onclick=guard(async()=>{
   if(!canCommand())throw Error('SEND 已关闭或控制状态已变化');commandPending=true;render();
   try{const a=await api.call('/api/visualization/confirm',{id:goal.id,target:api.target,allow_send:true});lastAction=a.id;notice('候选目标已提交现有 Action；等待实际确认。');await refresh();}
   finally{commandPending=false;render();}
  });row.append(button);root.append(row);
 }
}
function renderTools(){
 const panel=$('#tool-shortcuts');panel.replaceChildren();
 if(!state.tools?.agents?.length){panel.append(node('p','没有在线工具主机；启动已配置的 Desktop Agent 后自动连接。',{class:'muted small-note'}));return;}
 for(const id of ['qgroundcontrol','rviz2','gazebo']){
  const pair=state.tools.agents.flatMap(a=>a.tools.filter(t=>t.id===id).map(t=>[a,t])).sort((x,y)=>Number(y[0].connected)-Number(x[0].connected))[0];
  if(!pair)continue;const[a,t]=pair,i=t.instance,profile=i?.profile_id||state.tools.settings?.profiles?.[a.id+':'+id]?.profile_id||t.profiles[0],check=t.checks[profile],running=i?.process_running===true;
  const row=node('div',undefined,{class:'tool-shortcut'}),text=node('div');text.append(node('strong',t.name),node('small',!a.connected?'Agent 离线':running?(i.ready?'Ready':'运行中 · 数据就绪待确认'):check?.launchable?'可启动':'依赖 / 桌面不可用'));row.append(text);
  const button=node('button',running?'已运行':t.type==='gui'?'打开窗口':'启动后台');button.disabled=running||!a.connected||!check?.launchable||t.external_pids.length>0;button.title=running?'请在 Agent 桌面查看窗口；Tool Manager 可停止或重启。':t.external_pids.length?'已有外部进程，仅可观察。':'';
  button.onclick=guard(async()=>{
   if(id==='rviz2'&&t.profiles.includes(selected().kind)){
    const result=await api.call('/api/visualization/open',{target:api.target});notice('RViz2 Workspace · '+result.state+' · '+(result.error||result.agent_id));await refresh();return;
   }
   const saved=state.tools.settings?.context;const workspace=state.tools.workspaces?.runs?.find(r=>(r.spec?.context||r.context)?.vehicle_id===api.target&&r.state!=='STOPPED');
   const ctx=workspace?.spec?.context||workspace?.context||{vehicle_id:api.target,vehicle_type:selected().kind,environment:selected().owned_simulation?'simulation':'hardware_readonly',ros_namespace:saved?.vehicle_id===api.target?saved.ros_namespace:'/'+api.target.replace(/[^A-Za-z0-9_]/g,'_'),ros_domain_id:saved?.ros_domain_id??91,mavlink_profile:saved?.mavlink_profile||'monitor'};
   await api.call('/api/tools/operation',{agent_id:a.id,tool_id:id,profile_id:profile,operation:t.type==='gui'?'open':'launch',context:ctx});notice('工具请求已排队；实际运行与就绪状态由 Agent 确认。');await refresh();
  });row.append(button);panel.append(row);
 }
 if(!panel.childElementCount)panel.append(node('p','当前主机未注册 QGroundControl、RViz2 或 Gazebo 快捷入口；请在 Tool Manager 查看实际能力。',{class:'muted small-note'}));
}
$('#target').onchange=guard(async()=>{
 const target=$('#target').value;commandPending=true;$('#target').disabled=true;render();
 try{await loseControl();api.target=target;lastAction=null;targetHeight=null;await api.loadCatalog();await refresh();}
 finally{commandPending=false;$('#target').disabled=false;render();}
});
async function initialize(){
 await auth.ready;if(!auth.session)return;
 const vehicles=await api.call('/api/vehicles');$('#target').replaceChildren(...vehicles.map(v=>node('option',api.kindLabel(v.kind)+' / '+v.target,{value:v.target})));
 if(!vehicles.length){$('#vehicle-name').textContent='未装配车辆';notice('当前后端没有车辆。请使用已有的仿真启动入口。');return;}
 let requested='';try{requested=decodeURIComponent(location.hash.slice(1));}catch(_){}
 if(requested&&vehicles.some(v=>v.target===requested))$('#target').value=requested;
 else if(requested){$('#target').selectedIndex=-1;api.target=null;notice('指定车辆未注册或已结束，请从车辆列表选择当前实例。');live();return;}
 api.target=$('#target').value;await api.loadCatalog();await refresh();live();
}
setInterval(()=>update(),100);setInterval(()=>renew(),2000);setInterval(()=>{if(api.target&&!closing)refresh().catch(notice);if(lastReceived&&performance.now()-lastReceived>3500){invalidate();stop();}},1500);
initialize().catch(notice);
