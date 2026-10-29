'use strict';
// Uses the common browser session. Tools never receive vehicle SEND authority.
window.VAFVisualization=(()=>{
 function render(root,snapshot,target){
  if(!root)return;
  if(!root._view){
   const button=document.createElement('button'),status=document.createElement('p');button.textContent='打开 RViz2';button.className='primary';button.id='open-rviz';status.className='muted small-note';status.setAttribute('role','status');root.append(button,status);
   root._view={button,status,busy:false,target:null};
   button.onclick=async()=>{
    const view=root._view;if(view.busy||!view.target)return;view.busy=true;button.disabled=true;status.textContent='启动中 · 正在准备匹配的数据桥接与桌面 RViz2…';
    try{
     const target=view.target;let value;
     for(let attempt=0;attempt<30;attempt++){
      if(view.target!==target)throw Error('车辆上下文已改变，请重新打开');
      value=await window.VAFAuth.api('/api/visualization/open',{target});
      status.textContent=value.state+' · '+value.agent_id+(value.error?' · '+value.error:' · 查看 Tool Manager / Workspace 的实际就绪状态');
      if(value.state!=='SWITCHING')break;
      await new Promise(resolve=>setTimeout(resolve,1000));
     }
     if(value.state==='SWITCHING')throw Error('旧可视化退出尚未确认；请在 Workspace 查看实际状态。');
    }
    catch(e){status.textContent=e.message;status.dataset.tone='warning';}
    finally{view.busy=false;}
   };
  }
  const view=root._view;view.target=target;
  const vehicle=(snapshot?.vehicles||[]).find(v=>(v.target||v.id)===target),kind=vehicle?.kind||vehicle?.type;
  const agents=(snapshot?.tools?.agents||[]),eligible=agents.filter(a=>a.connected&&['visualization-bridge','rviz2'].every(id=>a.tools.some(t=>{
   const m=t.manifest||t,matching=Array.isArray(m.profiles)?m.profiles.includes(kind):!!m.profiles?.[kind];return m.id===id&&matching&&t.checks?.[kind]?.installed&&(id!=='rviz2'||t.checks[kind].desktop);
  })));
  const run=(snapshot?.tools?.workspaces?.runs||[]).filter(r=>r.spec?.context?.vehicle_id===target&&r.spec.id.startsWith('visualization-')&&r.state!=='STOPPED').at(-1);
  view.button.disabled=view.busy||!target||!eligible.length;
  if(view.busy)return;
  if(!eligible.length)view.status.textContent='不可用 · 需要在线桌面代理程序、ROS 2、匹配的数据桥接和 RViz 运行配置，以及图形环境。';
  else if(run)view.status.textContent=run.state+' · '+(run.error||'匹配车辆 '+target+'；窗口在 Agent 桌面，未嵌入网页。');
  else view.status.textContent='按当前车辆自动选择 Profile、ROS Domain 与 Namespace；数据未接通不会标记 Ready。';
 }
 return {render};
})();
