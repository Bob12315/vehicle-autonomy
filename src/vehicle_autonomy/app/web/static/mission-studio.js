'use strict';
const api=window.VAF, $=s=>document.querySelector(s);
let draft={schema_version:1,id:'mission',name:'新建任务',version:'1.0.0',target:'',root:'',nodes:[],blackboard:{},timeout_s:600};
let selected=null,connecting=null,zoom=1,undo=[],redo=[],state=null,runId=null,replaying=false;
const text=()=>JSON.stringify(draft);
const childLimits={Action:0,Wait:0,Sequence:32,Parallel:32,Fallback:32,Recovery:32,Timeout:1,Repeat:1,Event:1,Reactive:2,Condition:3};
const nodeName=n=>(n.type==='Action'?api.actionLabel(n.action):api.typeLabel(n.type))+'（'+n.id+'）';
function childHint(n){
 const max=childLimits[n.type];
 if(max===0)return nodeName(n)+'是叶子节点，不能连接子节点。要依次执行多个步骤，请添加“顺序执行”并将各步骤按顺序连接为它的子节点。';
 if(n.type==='Condition')return '条件判断可以不接分支，或按“真 / 假 / 未知”连接 2 或 3 个分支。';
 if(n.type==='Reactive')return '按顺序连接 2 个子节点：主任务、事件响应。';
 return max===1?'连接 1 个子节点，由该节点控制它的执行。':'按执行或分支顺序连接 1–32 个子节点。';
}
function clearConnection(){connecting=null;$('#connect-nodes').textContent='连接节点';}
function checkDraftChildren(){
 // Early editor feedback only; the server still validates the complete graph.
 for(const n of draft.nodes){
  if(n.type==='Action'){
   const spec=api.catalog.find(s=>s.name===n.action&&s.version===n.action_version);
   if(spec)api.validateParameters(spec.parameters,n.parameters||{},true);
  }
  if((n.children||[]).length>childLimits[n.type]){
   const message=childLimits[n.type]===0?childHint(n):nodeName(n)+'最多允许 '+childLimits[n.type]+' 个子节点，请在属性中断开多余连线。';
   $('#validation').textContent=message;throw Error(message);
  }
 }
}
function connectChild(parent,child){
 if(!parent)throw Error('父节点已不存在，请重新选择。');
 const children=parent.children||[];
 if(childLimits[parent.type]===0)throw Error(childHint(parent));
 if(parent.id===child.id)throw Error('不能把节点连接到自身。');
 if(children.includes(child.id))throw Error('这条连线已存在。');
 if(children.length>=childLimits[parent.type])throw Error(nodeName(parent)+'最多允许 '+childLimits[parent.type]+' 个子节点。');
 if(draft.nodes.some(n=>(n.children||[]).includes(child.id)))throw Error(nodeName(child)+'已有父节点，请先在原父节点属性中断开连线。');
 const visited=new Set(),pending=[child.id];
 while(pending.length){
  const id=pending.pop();if(id===parent.id)throw Error('该连线会形成循环，请使用“有限重复”节点表达重复执行。');
  if(visited.has(id))continue;visited.add(id);pending.push(...(draft.nodes.find(n=>n.id===id)?.children||[]));
 }
 change(()=>{parent.children=[...children,child.id];});
 $('#notice').textContent='已连接：'+nodeName(parent)+' → '+nodeName(child)+'。';
}
function remember(old){if(old!==text()){undo.push(old);if(undo.length>100)undo.shift();redo=[];$('#undo').disabled=!undo.length;$('#redo').disabled=!redo.length;}}
function change(fn){const old=text();fn();remember(old);render();}
function restore(raw){clearConnection();draft=JSON.parse(raw);$('#mission-id').value=draft.id;$('#mission-name').value=draft.name;$('#mission-version').value=draft.version;$('#mission-timeout').value=draft.timeout_s;render();}
function renderEdges(){
 const svg=$('#edges');svg.replaceChildren();
 for(const p of draft.nodes)for(const child of p.children||[]){
  const c=draft.nodes.find(n=>n.id===child);if(!c)continue;
  const a=p.position||{x:30,y:30},b=c.position||{x:240,y:30};
  const path=document.createElementNS('http://www.w3.org/2000/svg','path');
  path.setAttribute('d',`M ${a.x+165} ${a.y+44} C ${a.x+205} ${a.y+44},${b.x-40} ${b.y+44},${b.x} ${b.y+44}`);
  path.setAttribute('fill','none');path.setAttribute('stroke','#72bbb6');path.setAttribute('stroke-width','2');svg.append(path);
 }
}
function render(){
 $('#nodes').replaceChildren();
 $('#empty-graph').hidden=draft.nodes.length>0;
 $('#graph-summary').textContent=draft.nodes.length+' 个节点 · '+(draft.root?'根节点 '+draft.root:'未设置根节点');
 $('#undo').disabled=!undo.length;$('#redo').disabled=!redo.length;
 for(const n of draft.nodes){
  const pos=n.position||{x:30,y:30};n.position=pos;
  const el=api.node('div',undefined,{class:'graph-node'+(selected===n.id?' selected':''),'data-node-id':n.id,role:'button',tabindex:'0'});
  el.style.left=pos.x+'px';el.style.top=pos.y+'px';
  const heading=api.node('div',undefined,{class:'node-header'});heading.append(api.node('strong',n.type==='Action'?api.actionLabel(n.action):api.typeLabel(n.type)));
  if(draft.root===n.id)heading.append(api.node('span','根节点',{class:'root-badge'}));
  el.append(heading,api.node('small',n.id+' · '+(n.type==='Action'?n.action:n.type)),api.node('span','待执行',{class:'node-state'}));
  el.setAttribute('aria-label',(n.type==='Action'?api.actionLabel(n.action):api.typeLabel(n.type))+'，'+n.id);
  el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selected=n.id;render();}});
  el.addEventListener('pointerdown',e=>{
   if(e.button!==0)return;
   if(connecting!==null){
    const parent=draft.nodes.find(v=>v.id===connecting);clearConnection();
    try{connectChild(parent,n);}catch(error){api.report(error);}return;
   }
   selected=n.id;document.querySelectorAll('.graph-node').forEach(v=>v.classList.toggle('selected',v===el));properties();
   const old=text(),sx=e.clientX,sy=e.clientY,x=pos.x,y=pos.y;el.setPointerCapture(e.pointerId);
   const move=v=>{pos.x=Math.max(0,x+(v.clientX-sx)/zoom);pos.y=Math.max(0,y+(v.clientY-sy)/zoom);el.style.left=pos.x+'px';el.style.top=pos.y+'px';renderEdges();};
   el.addEventListener('pointermove',move);
   el.addEventListener('pointerup',()=>{el.removeEventListener('pointermove',move);remember(old);$('#json').value=JSON.stringify(draft,null,2);},{once:true});
  });
  $('#nodes').append(el);
 }
 renderEdges();properties();$('#json').value=JSON.stringify(draft,null,2);highlight();
}
function properties(){
 const panel=$('#properties');panel.replaceChildren();const n=draft.nodes.find(n=>n.id===selected);
 $('#selected-node').textContent=n?n.id:'未选择';
 const connect=$('#connect-nodes');connect.disabled=!n||childLimits[n.type]===0;
 connect.title=n?childHint(n):'请先选择父节点';
 if(!n){panel.textContent='点击画布中的节点，查看参数和连接。';return;}
 panel.append(api.node('p',childHint(n),{class:'muted',id:'child-rule'}));
 const title=api.node('div',undefined,{class:'property-title'});title.append(api.node('strong',n.type==='Action'?api.actionLabel(n.action):api.typeLabel(n.type)),api.node('small',n.id+' · '+n.type));panel.append(title);
 function field(name,value,set,type='text'){
  const label=api.node('label',api.fieldLabel(name)),input=api.node('input');input.type=type;input.value=value??'';input.name=name;
  input.addEventListener('change',()=>change(()=>set(type==='number'?Number(input.value):input.value)));label.append(input);panel.append(label);
 }
 field('timeout_s',n.timeout_s,v=>{if(v)n.timeout_s=v;else delete n.timeout_s;},'number');
 const edges=api.node('div');
 for(const [i,c] of n.children.entries()){
  const child=draft.nodes.find(v=>v.id===c);
  const row=api.node('div',`${i+1}. ${child?(child.type==='Action'?api.actionLabel(child.action):api.typeLabel(child.type)):c} · ${c} `,{class:'child-link'}),remove=api.node('button','断开');remove.onclick=()=>change(()=>n.children.splice(i,1));row.append(remove);edges.append(row);
 }panel.append(edges);
 if(n.type==='Action'){
  const s=api.catalog.find(s=>s.name===n.action&&s.version===(n.action_version||s.version));
  if(s){const semantics=api.node('details',undefined,{class:'technical-details'});semantics.append(api.node('summary','原始完成条件（英文）'),api.node('p',s.success_semantics,{class:'muted'}));panel.append(semantics);const form=api.node('div');form.id='node-parameters';
   api.parameters(form,s.parameters,n.parameters||={},()=>{remember(before);before=text();$('#json').value=JSON.stringify(draft,null,2);});let before=text();panel.append(form);}
  if(s){
   const box=api.node('details'),title=api.node('summary','类型化观测参数绑定');box.append(title);
   const fieldSelect=api.node('select',undefined,{id:'binding-field'});
   for(const key of Object.keys(s.parameters.properties))fieldSelect.append(api.node('option',key));
   const source=api.node('select',undefined,{id:'binding-source'});for(const v of ['world','blackboard'])source.append(api.node('option',v));
   const path=api.node('input',undefined,{id:'binding-path',placeholder:'vehicle.global_position.value.latitude_deg'});
   const frame=api.node('input',undefined,{id:'binding-frame',placeholder:'earth / odom / 留空'});
   const offset=api.node('input',undefined,{id:'binding-offset',type:'number',value:'0',step:'any'});
   const set=api.node('button','绑定参数'),clear=api.node('button','取消参数绑定');
   set.onclick=()=>change(()=>{const q={source:source.value,path:path.value,max_age_s:3};if(frame.value)q.frame=frame.value;if(Number(offset.value)!==0)q.offset=Number(offset.value);n.parameters[fieldSelect.value]={$query:q};});
   clear.onclick=()=>change(()=>delete n.parameters[fieldSelect.value]);
   for(const [name,control] of [['参数',fieldSelect],['来源',source],['路径',path],['坐标系',frame],['同单位偏移',offset]]){const l=api.node('label',name);l.append(control);box.append(l);}
   box.append(set,clear);panel.append(box);
  }
  field('output',n.output,v=>{if(v)n.output=v;else delete n.output;});
 }
 if(n.type==='Wait')field('duration_s',n.duration_s??1,v=>n.duration_s=v,'number');
 if(n.type==='Repeat')field('count',n.count??2,v=>n.count=v,'number');
 if(['Event','Reactive'].includes(n.type))field('event',n.event??'simulation.event',v=>n.event=v);
 if(n.type==='Parallel'){
  for(const [key,options]of [['completion',['all','any','main']],['failure',['fail_fast','all_failed']]]){
   const label=api.node('label',api.fieldLabel(key)),select=api.node('select');for(const o of options)select.append(api.node('option',({all:'全部完成',any:'任一完成',main:'主分支完成',fail_fast:'任一失败即退出',all_failed:'全部失败才失败'})[o],{value:o}));select.value=n[key]||options[0];select.onchange=()=>change(()=>n[key]=select.value);label.append(select);panel.append(label);
  }
 }
 if(n.type==='Condition'){
  n.expression ||= {op:'eq',source:'world',path:'vehicle.operation.armed',value:true,max_age_s:3};
  panel.append(api.node('p','连接顺序依次为：真 / 假 / 未知。条件仅支持受控类型表达式。',{class:'muted'}));
  for(const key of ['op','source','path','frame'])field(key,n.expression[key],v=>{if(v)n.expression[key]=v;else delete n.expression[key];});
  field('value (JSON scalar)',JSON.stringify(n.expression.value),v=>n.expression.value=JSON.parse(v));
 }
}
function add(type,action){
 change(()=>{
  let i=1;while(draft.nodes.some(n=>n.id==='n'+i))i++;
  const n={id:'n'+i,type,children:[],position:{x:30+(i%6)*210,y:30+Math.floor(i/6)*110}};
  if(type==='Action'){n.action=action.name;n.action_version=action.version;n.parameters={};}
  if(type==='Wait')n.duration_s=1;if(type==='Repeat')n.count=2;
  if(type==='Timeout')n.timeout_s=10;
  if(['Event','Reactive'].includes(type))n.event='simulation.event';
  draft.nodes.push(n);if(!draft.root)draft.root=n.id;selected=n.id;
 });
}
async function library(){const items=await api.call('/api/missions/library');$('#library').replaceChildren();for(const d of items)$('#library').append(api.node('option',d.name+' @ '+d.version,{value:d.id+'@'+d.version}));return items;}
async function refreshCatalog(){await api.loadCatalog();$('#action-library').replaceChildren();for(const s of api.catalog)$('#action-library').append(api.node('option',api.actionLabel(s.name)+' · '+api.kindLabel(s.kind),{value:s.name+'@'+s.version}));draft.target=api.target;}
$('#connect').onclick=api.guard(async()=>{await api.connect();await refreshCatalog();await library();render();await poll();});
$('#target').onchange=api.guard(refreshCatalog);
for(const type of ['Sequence','Parallel','Condition','Fallback','Recovery','Event','Reactive','Wait','Timeout','Repeat']){
 const definition=api.nodeTypes[type],b=api.node('button',undefined,{title:definition[2]});
 const content=api.node('span');content.append(api.node('strong',definition[0]),api.node('small',definition[2]));
 b.append(api.node('span',definition[1],{class:'node-icon','aria-hidden':'true'}),content);b.dataset.type=type;b.draggable=true;b.onclick=()=>add(type);b.ondragstart=e=>e.dataTransfer.setData('text/plain',type);$('#palette').append(b);
}
$('#graph-view').ondragover=e=>e.preventDefault();$('#graph-view').ondrop=e=>{e.preventDefault();const t=e.dataTransfer.getData('text/plain');if(['Sequence','Parallel','Condition','Fallback','Recovery','Event','Reactive','Wait','Timeout','Repeat'].includes(t))add(t);};
$('#add-sequence').onclick=()=>add('Sequence');
$('#add-action').onclick=()=>{const s=api.catalog.find(v=>v.name+'@'+v.version===$('#action-library').value);if(s)add('Action',s);};
for(const [selector,key]of [['#mission-id','id'],['#mission-name','name'],['#mission-version','version']])$(selector).onchange=()=>change(()=>draft[key]=$(selector).value);
$('#mission-timeout').onchange=()=>change(()=>draft.timeout_s=Number($('#mission-timeout').value));
$('#undo').onclick=()=>{if(undo.length){redo.push(text());restore(undo.pop());}};$('#redo').onclick=()=>{if(redo.length){undo.push(text());restore(redo.pop());}};
$('#connect-nodes').onclick=()=>{
 if(connecting!==null){clearConnection();return;}
 const parent=draft.nodes.find(n=>n.id===selected);
 if(!parent){api.report('请先选择父节点');return;}
 if(childLimits[parent.type]===0){api.report(childHint(parent));return;}
 if((parent.children||[]).length>=childLimits[parent.type]){api.report(nodeName(parent)+'的子节点数量已达上限，请先断开多余连线。');return;}
 connecting=parent.id;$('#connect-nodes').textContent='选择子节点 / 再点取消';$('#notice').textContent='父节点：'+nodeName(parent)+'。'+childHint(parent);
};
$('#root').onclick=()=>change(()=>{if(selected)draft.root=selected;});
$('#delete').onclick=()=>{clearConnection();change(()=>{draft.nodes=draft.nodes.filter(n=>n.id!==selected);for(const n of draft.nodes)n.children=n.children.filter(c=>c!==selected);if(draft.root===selected)draft.root=draft.nodes[0]?.id||'';selected=null;});};
$('#layout').onclick=()=>change(()=>{let row=0;const seen=new Set();function walk(id,depth){if(seen.has(id))return;seen.add(id);const n=draft.nodes.find(n=>n.id===id);if(!n)return;n.position={x:30+depth*210,y:30+row++*100};for(const c of n.children)walk(c,depth+1);}walk(draft.root,0);for(const n of draft.nodes)if(!seen.has(n.id))walk(n.id,0);});
function scale(){ $('#graph').style.transform=`scale(${zoom})`;$('#zoom-level').textContent=Math.round(zoom*100)+'%'; }$('#zoom-in').onclick=()=>{zoom=Math.min(2,zoom+.1);scale();};$('#zoom-out').onclick=()=>{zoom=Math.max(.3,zoom-.1);scale();};$('#fit').onclick=()=>{zoom=.8;scale();$('#graph-view').scrollTo(0,0);};
$('#validate').onclick=api.guard(async()=>{checkDraftChildren();$('#validation').textContent='校验通过\n'+JSON.stringify(await api.call('/api/missions/validate',{spec:draft}),null,2);});
$('#save').onclick=api.guard(async()=>{checkDraftChildren();draft=await api.call('/api/missions/save',{spec:draft});$('#validation').textContent='版本已保存';await library();render();});
$('#load').onclick=api.guard(async()=>{const key=$('#library').value;const d=(await library()).find(d=>d.id+'@'+d.version===key);if(d)change(()=>restore(JSON.stringify(d)));});
$('#export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(draft,null,2)],{type:'application/json'}));const a=api.node('a','',{href:url,download:draft.id+'.json'});a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('#import').onchange=api.guard(async()=>{const f=$('#import').files[0];if(!f||f.size>131072)throw Error('任务 JSON 不能超过 128 KiB');const raw=await f.text();change(()=>restore(raw));});
$('#apply-json').onclick=api.guard(()=>change(()=>restore($('#json').value)));
$('#start').onclick=api.guard(async()=>{checkDraftChildren();const p={spec:draft,allow_send:$('#send').checked};const c=$('#continuation').value.trim();if(c)p.continuation_of=c;$('#send').checked=false;const r=await api.call('/api/missions/start',p);runId=r.id;replaying=false;await poll();});
$('#cancel').onclick=api.guard(async()=>{if(runId)await api.call('/api/missions/cancel',{id:runId});await poll();});
$('#runs').onchange=()=>{runId=$('#runs').value;replaying=false;highlight();};$('#history-position').oninput=()=>{replaying=true;highlight();};
function highlight(){
 const r=state?.missions.find(r=>r.id===runId);if(!r)return;
 const slider=$('#history-position'),events=r.history||[];slider.max=events.length;if(!replaying)slider.value=events.length;
 const shown=events.slice(0,Number(slider.value)),statuses={};for(const e of shown)if(e.event==='node_state')statuses[e.node_id]=e.state;
 if(!replaying)for(const n of r.nodes)statuses[n.id]=n.state;
 document.querySelectorAll('.graph-node').forEach(n=>{n.dataset.state=statuses[n.dataset.nodeId]||'IDLE';n.querySelector('.node-state').textContent=api.stateLabel(n.dataset.state);});
 $('#run-summary').textContent=api.stateLabel(r.state)+' · '+(r.release_safe?'已取得安全退出证据':'尚未确认安全退出')+(r.error?' · '+r.error:'');
 $('#run-detail').textContent=JSON.stringify({id:r.id,state:r.state,release_safe:r.release_safe,continuation:r.continuation_of,error:r.error,events:shown.slice(-8)},null,2);
 $('#feedback').textContent=JSON.stringify(state.actions.filter(a=>r.action_ids.includes(a.id)).map(a=>({id:a.id,state:a.state,feedback:a.feedback.slice(-3),error:a.error,safety:a.safety})),null,2);
}
async function poll(){
 state=await api.call('/api/studio/state');$('#runs').replaceChildren();for(const r of state.missions)$('#runs').append(api.node('option',api.stateLabel(r.state)+' · '+r.id,{value:r.id}));
 if(!runId&&state.missions.length)runId=state.missions.at(-1).id;$('#runs').value=runId||'';highlight();
}
setInterval(()=>{if(api.target)poll().catch(api.report);},700);render();

window.VAFAuth.ready.then(s=>{if(s)$('#connect').click();});
