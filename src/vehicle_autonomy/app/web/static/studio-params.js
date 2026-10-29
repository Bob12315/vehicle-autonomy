'use strict';
window.StudioParams=(()=>{
 const {el,json}=StudioDOM;
 function initial(s){if('default'in s)return structuredClone(s.default);if('const'in s)return s.const;if(s.enum)return s.enum[0];if(s.anyOf)return initial(s.anyOf[0]);if(s.type==='object')return Object.fromEntries(Object.entries(s.properties||{}).filter(([k,v])=>s.required?.includes(k)||'default'in v).map(([k,v])=>[k,initial(v)]));if(s.type==='array')return s.prefixItems?s.prefixItems.map(initial):Array.from({length:Math.min(s.minItems||0,4096)},()=>initial(s.items||{type:'string'}));return {boolean:false,integer:0,number:0,string:'',null:null}[s.type];}
 function field(schema,value,change,path='value'){
  const L=StudioLocale,ui=schema['x-ui']||{},scale=ui.scale||1;schema={...schema,...ui.bounds};
  const wrap=el('div',undefined,{class:'field-row','data-original-text':''});
  const details=el('small',undefined,{class:'parameter-contract','data-original-text':''});
  const bounds=[];for(const [k,symbol]of [['minimum','≥'],['exclusiveMinimum','>'],['maximum','≤'],['exclusiveMaximum','<']])if(schema[k]!==undefined)bounds.push(symbol+' '+L.number(schema[k],scale));
  details.textContent=(schema['x-required']?L.word('required'):L.word('optional'))+' · '+L.word('originalField')+' '+path+(ui.unit?' · '+L.word('unit')+' '+ui.unit:'')+(bounds.length?' · '+L.word('range')+' '+bounds.join(' / '):['number','integer'].includes(schema.type)?' · '+L.word('unknownRange'):'')+('default'in schema?' · '+L.word('default')+' '+(typeof schema.default==='number'?L.number(schema.default,scale):JSON.stringify(schema.default)):'');wrap.append(details);
  if(ui.description||schema.description)wrap.append(el('p',ui.description||schema.description,{class:'parameter-help','data-original-text':''}));
  if(schema.anyOf){const pick=el('select',undefined,{'aria-label':path+' 类型'}),slot=el('div');let selected=schema.anyOf.findIndex(s=>s.type===(value===null?'null':Array.isArray(value)?'array':typeof value==='number'&&Number.isInteger(value)?'integer':typeof value));if(selected<0)selected=0;schema.anyOf.forEach((s,i)=>pick.append(el('option',s.title||s.type||JSON.stringify(s.const),{value:i,'data-original-text':''})));pick.value=selected;const draw=()=>{slot.replaceChildren(field(schema.anyOf[Number(pick.value)],value,change,path));};pick.onchange=()=>{value=initial(schema.anyOf[Number(pick.value)]);change(value);draw();};wrap.append(pick,slot);draw();return wrap;}
  if(schema.type==='object'){
   const box=el('div',undefined,{class:'typed-object'});value=value&&typeof value==='object'?value:{};
   for(const [name,s] of Object.entries(schema.properties||{})){const row=el('div',undefined,{class:'field-row'});row.append(el('label',(s['x-ui']?.label||s.title||L.text(name))+(s['x-ui']?.unit?' ('+s['x-ui'].unit+')':'')+(schema.required?.includes(name)?' *':'')),field(s,value[name]??initial(s),v=>{value={...value,[name]:v};change(value);},path+'.'+name));box.append(row);}
   if(!Object.keys(schema.properties||{}).length){const input=el('textarea');input.value=JSON.stringify(value,null,2);input.setAttribute('aria-label',path);input.onchange=()=>{try{const parsed=JSON.parse(input.value);if(parsed===null||Array.isArray(parsed)||typeof parsed!=='object')throw Error();input.setCustomValidity('');change(parsed);}catch{input.setCustomValidity(StudioLocale.word('objectError'));input.reportValidity();}};box.append(input);}wrap.append(box);return wrap;
  }
  if(schema.type==='array'){
   value=Array.isArray(value)?value:[];const box=el('div',undefined,{class:'typed-array'});function draw(){box.replaceChildren();value.forEach((item,i)=>{const row=el('div',undefined,{class:'array-item'}),remove=el('button','移除 '+(i+1));remove.type='button';remove.disabled=Boolean(schema.prefixItems)||value.length<=(schema.minItems||0);remove.onclick=()=>{value=value.filter((_,j)=>j!==i);change(value);draw();};row.append(field(schema.prefixItems?.[i]||schema.items||{type:'string'},item,v=>{value=value.map((x,j)=>i===j?v:x);change(value);},path+'.'+i),remove);box.append(row);});const add=el('button','＋ 添加项');add.type='button';add.disabled=Number.isFinite(schema.maxItems)&&value.length>=schema.maxItems;add.onclick=()=>{value=[...value,initial(schema.prefixItems?.[value.length]||schema.items||{type:'string'})];change(value);draw();};box.append(add);}draw();wrap.append(box);return wrap;
  }
  let input;
  if(schema.enum||'const'in schema){input=el('select');const values=schema.enum||[schema.const];values.forEach((v,i)=>input.append(el('option',StudioLocale.text(String(v)),{value:i,'data-original-text':''})));input.value=Math.max(0,values.findIndex(v=>v===value));input.onchange=()=>change(values[Number(input.value)]);}
  else if(schema.type==='null'){input=el('span','null');}
  else {input=el('input');input.type=schema.type==='boolean'?'checkbox':['integer','number'].includes(schema.type)?'number':'text';
   if(input.type==='checkbox')input.checked=Boolean(value);else input.value=typeof value==='number'?L.number(value,scale):value??'';
   if(input.type==='number'){input.step=schema.type==='integer'&&scale===1?'1':'any';if(schema.minimum!==undefined)input.min=L.number(schema.minimum,scale);if(schema.maximum!==undefined)input.max=L.number(schema.maximum,scale);}
   if(schema.maxLength)input.maxLength=schema.maxLength;if(schema.pattern)input.pattern=schema.pattern;
   const message=el('span','',{class:'parameter-error',role:'alert','data-original-text':''});wrap.append(message);input.required=Boolean(schema['x-required']);
   input.oninput=()=>{input.setCustomValidity('');message.textContent='';};
   input.onchange=()=>{input.setCustomValidity('');let result=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value,error='';
    if(input.type!=='checkbox'&&input.required&&!input.value.trim())error=L.word('requiredError');
    if(!error&&input.type==='number'){
     if(!Number.isFinite(result)||input.validity.badInput)error=L.word('numberError');
     else if(scale===1e-9){const match=/^([+-]?)([0-9]+)(?:\.([0-9]{1,9}))?$/.exec(input.value);if(!match)error=L.word('timeError');else{const ns=(BigInt(match[2])*1000000000n+BigInt((match[3]||'').padEnd(9,'0')))*(match[1]==='-'?-1n:1n);result=Number(ns);if(!Number.isSafeInteger(result))error=L.word('timeError');}}
     else result/=scale;
     if(!error&&schema.type==='integer'&&!Number.isInteger(result))error=L.word('integerError');
     if(!error&&(['minimum','maximum','exclusiveMinimum','exclusiveMaximum'].some(k=>schema[k]!==undefined&&!({minimum:result>=schema[k],maximum:result<=schema[k],exclusiveMinimum:result>schema[k],exclusiveMaximum:result<schema[k]}[k]))))error=L.word('rangeError');
    }
    if(!error&&(!input.validity.valid||schema.maxLength&&input.value.length>schema.maxLength))error=L.word('rangeError');
    if(error){input.setCustomValidity(error);message.textContent=error;input.reportValidity();return;}change(result);
   };}
  input.setAttribute('aria-label',path);if(schema.readOnly)input.disabled=true;wrap.append(input);return wrap;
 }
 function compatible(a,b){if(!a||!b)return false;if(a.anyOf)return a.anyOf.every(s=>compatible(s,b));if(b.anyOf)return b.anyOf.some(s=>compatible(a,s));if(a.type!==b.type&&!(a.type==='integer'&&b.type==='number'))return false;if(b.type==='array')return compatible(a.items,b.items);if(b.type==='object')return(b.required||[]).every(k=>a.properties?.[k]&&compatible(a.properties[k],b.properties?.[k]||{}));return Boolean(a.type);}
 function options(doc,node,catalog){
  const list=[];function add(root,s,depth=0){list.push({ref:root,schema:s});if(depth<4)for(const [key,child]of Object.entries(s.properties||{}))add(root+'.'+key,child,depth+1);}
  for(const [key,d]of Object.entries(doc.blackboard||{}))add('mission.'+key,d.schema);
  for(const [key,d]of Object.entries(doc.interface?.inputs||{}))add('submission.'+key,d.schema);
  for(const other of doc.nodes){if(other.node_id===node.node_id)continue;const s=catalog.actions.find(a=>a.name===other.action_type&&(!other.action_contract_version||a.version===other.action_contract_version))?.output;if(s)add('node.'+other.node_id+'.output',s);}
  // Loop references are accepted only where the backend proves their scope.
  for(const loop of doc.nodes.filter(n=>n.type==='ForEach')){const ref=loop.execution_policy?.collection?.ref;const variable=ref?.startsWith('mission.')?doc.blackboard?.[ref.split('.')[1]]:null;if(variable?.schema.items)add('loop.current_item',variable.schema.items);}
  add('loop.index',{type:'integer'});add('loop.iteration_id',{type:'string'});return list;
 }
 function bindField(name,schema,node,doc,catalog,change){
  const row=el('div',undefined,{class:'field-row'});row.append(el('label',(schema['x-ui']?.label||schema.title||StudioLocale.text(name))+(schema['x-ui']?.unit?' ('+schema['x-ui'].unit+')':'')+(schema['x-required']?' *':'')));
  const source=el('select',undefined,{class:'field-source','aria-label':name+' 输入来源'});for(const [value,label]of [['fixed','固定值'],['blackboard','Blackboard'],['upstream','上游 Action 输出'],['world','外部只读状态'],['tool','外部 Tool 导入']])source.append(el('option',label,{value}));
  source.querySelector('option[value=tool]').disabled=!(node.action_type==='Goto'&&['x_m','y_m','z_m'].includes(name));source.querySelector('option[value=tool]').title='当前支持 Goto 的 RViz odom 位置数据；QGC 导入未装配';
  const binding=node.input_bindings?.[name];source.value=binding?.source==='external'?'tool':binding?.source==='world'?'world':binding?.ref?.startsWith('node.')?'upstream':binding?'blackboard':'fixed';const slot=el('div');
  function setBinding(value){change(()=>{node.input_bindings??={};node.parameters??={};if(value){node.input_bindings[name]=value;delete node.parameters[name];}else delete node.input_bindings[name];});}
  function draw(){slot.replaceChildren();if(source.value==='fixed'){slot.append(field(schema,node.parameters?.[name]??initial(schema),value=>change(()=>{node.parameters??={};node.parameters[name]=value;if(node.input_bindings)delete node.input_bindings[name];}),name));return;}
   if(source.value==='tool'){const select=el('select',undefined,{'aria-label':name+' Tool 目标'});select.append(el('option','选择当前 RViz odom 目标',{value:''}));const hint=el('p','正在读取候选目标…',{class:'muted'});slot.append(select,hint);VAFAuth.api('/api/studio-b/inputs/goals',{target:doc.target}).then(value=>{for(const goal of value.goals.filter(g=>g.frame==='odom'))select.append(el('option',goal.id+' · '+Math.floor(goal.remaining_s)+'s · '+goal.position.join(', '),{value:goal.id}));select.value=binding?.id||'';hint.textContent=value.limitations;}).catch(error=>hint.textContent=error.message);select.onchange=()=>{if(select.value)setBinding({source:'external',provider:'navigation_goal',id:select.value,path:'position.'+name[0],frame:'odom',max_age_s:30});};return;}
   const input=el('input',undefined,{'aria-label':name+' 变量引用',list:'refs_'+node.node_id+'_'+name});input.value=binding?.ref||binding?.path||'';input.placeholder=source.value==='world'?'vehicle.operation.armed':'mission.variable';const choices=el('datalist',undefined,{id:input.getAttribute('list')}),available=source.value==='world'?Object.entries(catalog.world_bindings||{}).map(([ref,schema])=>({ref,schema})):options(doc,node,catalog);for(const option of available.filter(o=>compatible(o.schema,schema)&&(source.value==='world'||(source.value==='upstream'?o.ref.startsWith('node.'):!o.ref.startsWith('node.')))))choices.append(el('option',undefined,{value:option.ref}));input.onchange=()=>setBinding(source.value==='world'?{source:'world',path:input.value,max_age_s:3}:{ref:input.value});slot.append(input,choices);
  }source.onchange=()=>{setBinding(source.value==='fixed'?null:source.value==='tool'?{source:'external',provider:'navigation_goal',id:'',path:'position.'+name[0],frame:'odom',max_age_s:30}:source.value==='world'?{source:'world',path:'',max_age_s:3}:{ref:''});draw();};row.append(source,slot);draw();return row;
 }
 function jsonField(label,value,change){const row=el('label',label),area=el('textarea');area.value=JSON.stringify(value,null,2);area.setAttribute('aria-label',label);area.onchange=()=>{try{const parsed=JSON.parse(area.value);area.setCustomValidity('');change(parsed);}catch(error){area.setCustomValidity(StudioLocale.word('jsonError'));area.reportValidity();}};row.append(area);return row;}
 function condition(value,change){const box=el('div'),e=value||{op:'eq',source:'blackboard',path:'mission.ready',value:true};
  for(const [key,s]of Object.entries({source:{type:'string',enum:['blackboard','world']},path:{type:'string'},op:{type:'string',enum:['eq','ne','lt','le','gt','ge']},value:{anyOf:[{type:'boolean'},{type:'number'},{type:'string'}]}})){const label=el('label',key);label.append(field(s,e[key],v=>change({...e,[key]:v}),'condition.'+key));box.append(label);}return box;
 }
 return{field,initial,compatible,options,bindField,jsonField,condition};
})();
