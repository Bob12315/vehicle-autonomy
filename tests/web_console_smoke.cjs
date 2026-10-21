// Synthetic DOM behavioral checks; deliberately not a browser visual acceptance.
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const source = fs.readFileSync(process.argv[2] || 'web_ui/static/console.js', 'utf8');
const nodes = new Map(), calls = [], responses = [], timers = [];
const node = () => ({value:'',checked:false,disabled:false,textContent:'',children:[],
  append(x) { this.children.push(x); if(x.value && !this.value)this.value=x.value; },
  replaceChildren() { this.children=[]; this.value=''; }, removeAttribute() {}});
const get = id => { if(!nodes.has(id))nodes.set(id,node()); return nodes.get(id); };
const sandbox = {document:{getElementById:get,createElement:node,createTextNode:x=>x},
  crypto:{randomUUID:()=> 'test-request'},
  fetch:async(path,options)=>{calls.push({path,options});return {json:async()=>({ok:true,result:responses.shift()})};},
  setInterval:fn=>timers.push(fn),Date,JSON};
vm.createContext(sandbox);
new vm.Script(source,{filename:'console.js'}).runInContext(sandbox);
const check = (condition,message) => { if(!condition)throw Error(message); };
(async()=>{
  get('token').value='test-token';
  responses.push({state:'READY',profile:'rover_sim',session_id:'sim-session',connected:true,
    vehicle:{armed:false}},['disarmed_mode']);
  await get('connect').onclick(); check(get('token').value==='','token input retained');
  get('intent').value='HOLD twice';
  responses.push({id:'proposal',kind:'design',decision:'propose',steps:[{mission:'disarmed_mode'}],preflight:{eligible:true}});
  await get('design').onclick();
  check(calls.at(-1).path==='/api/design' && !get('approve').disabled,'design route/admission');
  check(get('proposal-steps').children.length===1 && get('proposal-steps').children[0].textContent==='disarmed_mode',
    'reviewable ordered mission steps missing');
  const before=calls.length; await get('approve').onclick();
  check(calls.length===before,'missing confirmation sent request');
  get('human').checked=true; responses.push({task_id:'design:one'});
  await get('approve').onclick();
  check(calls.at(-1).path==='/api/design/approve' && get('approve').disabled,'design approval route');
  check(calls.at(-1).options.headers['X-VAF-CSRF']==='test-token','CSRF header missing');
  const previous=calls.length;get('example').value='courier';get('fill-example').onclick();
  check(get('intent').value.includes('DOCK') && calls.length===previous,'example unexpectedly executed');
  responses.push({id:'parameters',kind:'design',decision:'propose',
    steps:[{mission:'motion:drive',parameters:{distance_m:10,speed_mps:.15}}],preflight:{eligible:true}});
  await get('design').onclick();
  check(get('proposal-steps').children[0].textContent.includes('10 米'),'parameterized preview missing');
  responses.push({id:'blocked',kind:'design',decision:'propose',preflight:{eligible:false,reasons:['not_ready']}});
  await get('design').onclick();check(get('approve').disabled,'failed preflight enabled approval');
  responses.push({state:'READY',mode:'hardware_readonly',connected:true});await timers[0]();
  check(get('start').disabled && get('approve').disabled,'readonly controls enabled');
  console.log(JSON.stringify({passed:true,source_sha256:crypto.createHash('sha256').update(source).digest('hex'),
    checks:['syntax','design_button_route','reviewable_steps','explicit_confirmation','design_approval_route',
      'csrf_header','example_does_not_execute','parameterized_preview','failed_preflight_disabled','readonly_disabled','token_input_cleared'],visual_qa:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
