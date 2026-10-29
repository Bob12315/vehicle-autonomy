'use strict';
// Registry identities are never translated. Only presentation values cross here.
window.StudioLocale=(()=>{
 const words={
  search:['搜索中文名称、动作 ID 或参数说明','Search name, Action ID or parameter help'],
  current:['当前车型','Current vehicle'],allVehicles:['全部车型','All vehicles'],provider:['全部能力提供方','All providers'],
  all:['全部可用性','All availability'],available:['仅可配置','Configurable only'],unavailable:['不可配置','Unavailable'],
  configurable:['可配置 · 执行时检查','Configurable · admission checked'],favorite:['收藏','Favorite'],unfavorite:['取消收藏','Unfavorite'],
  favorites:['常用动作','Favorites'],recent:['最近使用','Recently used'],noFavorites:['尚未收藏动作','No favorite Actions'],noRecent:['尚未添加动作','No recent Actions'],
  empty:['没有匹配的动作。请调整搜索、车型或能力提供方筛选。','No matching Actions. Adjust search, vehicle or provider filters.'],
  noActions:['当前筛选下暂无动作','No Actions for these filters'],original:['原始动作标识','Original Action ID'],supports:['支持车型','Supported vehicles'],
  required:['必填','Required'],optional:['可选','Optional'],default:['默认值','Default'],range:['范围','Range'],unit:['单位','Unit'],
  originalField:['原始字段','Original field'],unknownRange:['未声明数值范围；执行时仍须校验','No numeric range declared; admission still validates'],
  requiredError:['请填写此必填参数','This parameter is required'],numberError:['请输入有限数值','Enter a finite number'],
  integerError:['请输入整数','Enter an integer'],rangeError:['参数超出允许范围','Parameter outside the allowed range'],
  timeError:['请输入最多九位小数的秒数，且不得超过安全整数纳秒范围','Enter decimal seconds with at most nine fractional digits within safe integer nanoseconds'],
  jsonError:['请输入有效的 JSON','Enter valid JSON'],objectError:['请输入对象 JSON','Enter a JSON object'],
  in_process:['进程内动作','In-process Actions'],managed:['受控外部能力','Managed external capabilities'],nav2:['原生 Nav2','Native Nav2'],opaque:['未明确生命周期契约','Unverified lifecycle contract'],
  rover:['地面车','Rover'],copter:['多旋翼','Copter'],plane:['固定翼','Plane'],external:['外部任务','External job'],
 };
 const nodes={Start:['开始','Start'],End:['结束','End'],Condition:['条件判断','Condition'],ForEach:['遍历循环','For each'],Loop:['循环','Loop'],Parallel:['并行执行','Parallel'],Join:['并行汇合','Join'],Wait:['等待','Wait'],SubMission:['子任务','Sub-mission'],Sequence:['顺序执行','Sequence'],Recovery:['故障恢复','Recovery'],Retry:['有限重试','Retry']};
 const ports={next:['下一步','Next'],body:['循环体','Body'],true:['条件成立','True'],false:['条件不成立','False'],unknown:['状态未知','Unknown'],success:['成功','Success'],failure:['失败','Failure'],timeout:['超时','Timeout'],try:['尝试','Try'],recover:['恢复','Recover']};
 const states={PENDING:['等待执行','Pending'],RUNNING:['正在执行','Running'],SUCCEEDED:['执行成功','Succeeded'],FAILED:['执行失败','Failed'],TIMED_OUT:['执行超时','Timed out'],CANCELLING:['正在请求取消','Cancel requested'],CANCEL_REQUESTED:['正在请求取消','Cancel requested'],CANCELLED:['已取消','Cancelled'],SKIPPED:['已跳过','Skipped'],PAUSED:['已暂停','Paused'],UNKNOWN:['未知','Unknown'],UNCONFIRMED:['未确认','Unconfirmed']};
 let locale='zh-CN';
 try{locale=localStorage.getItem('vaf.studio.locale')==='en-US'?'en-US':'zh-CN';}catch{}
 const pick=v=>typeof v==='object'&&v!==null?(v[locale]??v['en-US']??v['zh-CN']??''):v;
 const word=k=>words[k]?.[locale==='zh-CN'?0:1]??k;
 function text(v){if(v===undefined||v===null)return v;const key=String(v),state=key.replace(/[ -]/g,'_').toUpperCase();return (Object.hasOwn(nodes,key)?nodes[key]:Object.hasOwn(states,state)?states[state]:null)?.[locale==='zh-CN'?0:1]??(locale==='zh-CN'?VAFI18n.text(v):v);}
 function port(v){return ports[v]?.[locale==='zh-CN'?0:1]??text(v);}
 function set(value){locale=value==='en-US'?'en-US':'zh-CN';try{localStorage.setItem('vaf.studio.locale',locale);}catch{};window.dispatchEvent(new Event('studio:locale'));}
 function number(value,scale=1){if(scale===1e-9&&Number.isSafeInteger(value)){const raw=BigInt(value),sign=raw<0n?'-':'',ns=raw<0n?-raw:raw,whole=ns/1000000000n,part=String(ns%1000000000n).padStart(9,'0').replace(/0+$/,'');return sign+whole+(part?'.'+part:'');}return String(value*scale);}
 function action(meta){return pick(meta?.presentation?.display_name)||meta?.name||'';}
 function schema(original,meta){
  const copy=structuredClone(original),fields=meta?.presentation?.parameters||{};
  function walk(s,key){if(key){const info=fields[key];s['x-ui']=info?{label:pick(info.label),description:pick(info.description),unit:info.display_unit||info.unit||'',scale:info.display_scale||1,bounds:info.bounds||{},originalUnit:info.unit||''}:{label:locale==='zh-CN'?VAFI18n.field(key):key,description:s.description||'',scale:1};}
   for(const [k,p]of Object.entries(s.properties||{})){walk(p,k);p['x-required']=(s.required||[]).includes(k);}
   for(const child of s.anyOf||[])walk(child,key);if(s.items)walk(s.items);for(const child of s.prefixItems||[])walk(child);
  }walk(copy);return copy;
 }
 return {pick,word,text,port,set,action,schema,number,get locale(){return locale;}};
})();

window.StudioActionLibrary=class{
 constructor(root,{add,logic,submissions}){
  this.root=root;this.callbacks={add,logic,submissions};this.catalog=null;this.target='';this.query='';this.kind='current';this.provider='';this.availability='';
  this.saved={favorites:[],recent:[],closed:['favorites','recent','logic']};
  try{const value=JSON.parse(localStorage.getItem('vaf.studio.palette')||'{}');for(const key of Object.keys(this.saved))if(Array.isArray(value[key]))this.saved[key]=value[key].filter(v=>typeof v==='string'&&v.length<256).slice(0,100);}catch{}
 }
 save(){try{localStorage.setItem('vaf.studio.palette',JSON.stringify(this.saved));}catch{}}
 key(a){return a.name+'@'+a.version;}
 update(catalog,target){this.catalog=catalog;this.target=target;this.render();}
 actions(){return this.catalog?.library_sets?.[this.target]||this.catalog?.actions||[];}
 remember(action){const key=this.key(action);this.saved.recent=[key,...this.saved.recent.filter(v=>v!==key)].slice(0,12);this.save();}
 el(tag,text,attrs={}){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);return e;}
 render(){
  if(!this.catalog)return;const L=StudioLocale,root=this.root;root.replaceChildren();root.setAttribute('data-original-text','');
  const filters=this.el('div',undefined,{class:'palette-filters'});
  const select=(id,values,current,change)=>{const control=this.el('select',undefined,{id,'aria-label':id});for(const [value,label]of values)control.append(this.el('option',label,{value}));control.value=current;control.onchange=()=>{change(control.value);this.render();};filters.append(control);};
  select('palette-vehicle',[['current',L.word('current')],['all',L.word('allVehicles')],...['rover','copter','plane','external'].map(v=>[v,L.word(v)])],this.kind,v=>this.kind=v);
  const providers=[...new Set(this.actions().map(a=>a.presentation?.provider_id||'opaque'))];
  select('palette-provider',[['',L.word('provider')],...providers.map(v=>[v,L.word(v)])],this.provider,v=>this.provider=v);
  select('palette-availability',[['',L.word('all')],['available',L.word('available')],['unavailable',L.word('unavailable')]],this.availability,v=>this.availability=v);
  root.append(filters);
  const actual=this.catalog.vehicles.find(v=>v.target===this.target)?.kind;
  const kind=this.kind==='current'?actual:this.kind==='all'?'':this.kind;
  const query=this.query.toLocaleLowerCase();
  const matches=a=>{
   const p=a.presentation||{},fields=Object.entries(p.parameters||{}).flatMap(([k,v])=>[k,...Object.values(v.label||{}),...Object.values(v.description||{})]);
   const haystack=[a.name,a.version,a.description,...Object.values(p.display_name||{}),...Object.values(p.description||{}),...fields,...(p.tags||[]).flatMap(v=>Object.values(v))].join(' ').toLocaleLowerCase();
   return (!kind||!p.vehicles?.length||p.vehicles.includes(kind))&&(!this.provider||p.provider_id===this.provider)&&(!this.availability||(this.availability==='available')===Boolean(a.availability?.configurable))&&haystack.includes(query);
  };
  const items=this.actions().filter(matches),make=(a,section)=>{
   const p=a.presentation||{},available=a.availability?.configurable===true;
   const row=this.el('div',undefined,{class:'palette-action','data-action-key':this.key(a)});
   const button=this.el('button',undefined,{class:'palette-item','data-action-id':a.name,'data-section':section,type:'button',draggable:String(available)});
   button.disabled=!available;button.append(this.el('strong',L.action(a)),this.el('small',a.name+' · '+a.version,{class:'original-action-id'}),this.el('small',L.pick(p.description)||a.description,{class:'action-description',title:L.pick(p.description)||a.description}));
   if(p.classification_reason)button.append(this.el('small',L.pick(p.classification_reason)));
   const tags=this.el('span',undefined,{class:'action-tags'});for(const tag of p.tags||[])tags.append(this.el('span',L.pick(tag)));button.append(tags);
   button.append(this.el('small',L.word('supports')+'：'+(p.vehicles?.map(v=>L.word(v)).join(' / ')||'—')),
    this.el('small',L.word(p.provider_id||'opaque')+' · '+L.pick(p.provider_description),{class:'action-provider',title:L.pick(p.provider_description)}),this.el('small',available?L.word('configurable'):(a.availability?.reasons||[]).map(L.pick).join('；')||L.word('unavailable'),{class:available?'availability-good':'availability-warning'}));
   button.onclick=()=>{if(!available)return;this.remember(a);this.callbacks.add(a);this.render();};
   button.ondragstart=e=>{if(!available){e.preventDefault();return;}e.dataTransfer.setData('application/vaf-node',JSON.stringify({type:'Action',action_type:a.name,action_contract_version:a.version}));};
   const starred=this.saved.favorites.includes(this.key(a)),star=this.el('button',starred?'★':'☆',{class:'action-favorite',type:'button','aria-label':L.word(starred?'unfavorite':'favorite')+' '+L.action(a),'aria-pressed':String(starred)});
   star.onclick=()=>{const set=new Set(this.saved.favorites);if(starred)set.delete(this.key(a));else set.add(this.key(a));this.saved.favorites=[...set];this.save();this.render();};row.append(button,star);return row;
  };
  const section=(key,label,children)=>{const box=this.el('details',undefined,{class:'action-category','data-category':key});box.open=Boolean(this.query)||!this.saved.closed.includes(key);box.append(this.el('summary',label+' · '+children.length));box.append(...children);box.ontoggle=()=>{if(this.query)return;const set=new Set(this.saved.closed);if(box.open)set.delete(key);else set.add(key);this.saved.closed=[...set];this.save();};root.append(box);return box;};
  for(const [key,word]of [['favorites','favorites'],['recent','recent']]){const list=this.saved[key].map(k=>items.find(a=>this.key(a)===k)).filter(Boolean);const box=section(key,L.word(word),list.map(a=>make(a,key)));if(!list.length)box.append(this.el('p',L.word(key==='favorites'?'noFavorites':'noRecent'),{class:'muted palette-empty'}));}
  const category=this.catalog.categories||{};
  const logic=[];for(const [type,meta]of Object.entries(this.catalog.node_types||{}))if(type!=='Action'&&type!=='SubMission'&&[type,L.text(type)].join(' ').toLocaleLowerCase().includes(query))logic.push(this.callbacks.logic(type,meta));
  section('logic',(category.logic?.icon||'')+' '+L.pick(category.logic?.label||'logic'),logic);
  for(const [key,meta]of Object.entries(category))if(!['logic','submission'].includes(key)){const list=items.filter(a=>(a.presentation?.category||'uncategorized')===key);if(!list.length&&query)continue;const box=section(key,meta.icon+' '+L.pick(meta.label),list.map(a=>make(a,key)));if(!list.length)box.append(this.el('p',L.word('noActions'),{class:'muted palette-empty'}));}
  if(!items.length)root.append(this.el('p',L.word('empty'),{class:'palette-empty',role:'status'}));
  const sub=section('submission',(category.submission?.icon||'')+' '+L.pick(category.submission?.label||'submission'),[]);this.callbacks.submissions(sub);
  const search=document.querySelector('#palette-search');if(search)search.placeholder=L.word('search');
 }
};
