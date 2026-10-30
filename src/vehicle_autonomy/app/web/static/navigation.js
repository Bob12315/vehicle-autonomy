'use strict';
// One menu for all Mission/Control Center pages. Visibility is not authorization.
window.VAFNavigation=(()=>{
 let state=null;
 const remoteViews=new Set(['tools','workspaces','logs','settings']);
 function element(tag,text,className){const e=document.createElement(tag);if(text)e.textContent=text;if(className)e.className=className;return e;}
 function active(id){
  if(location.pathname==='/console')return id===(location.hash.slice(1)||'dashboard');
  return id===({'/center':'center','/simulation':'simulation','/control':'control','/studio':'studio','/':'actions'}[location.pathname]);
 }
 function highlight(){for(const a of document.querySelectorAll('[data-navigation] [data-nav-id]')){
  if(active(a.dataset.navId))a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');
 }}
 function canonical(){
  if(!state)return false;
  if(location.pathname==='/center'&&!state.local){location.replace('/console#dashboard');return true;}
  if(location.pathname!=='/console')return false;
  const view=location.hash.slice(1);
  if(!remoteViews.has(view)||state.remote)return false;
  if(state.local){location.replace('/center'+({tools:'#tools',logs:'#tool-logs',settings:'#system-panel',workspaces:'#tools'}[view]));return true;}
  location.replace('/console#dashboard');return true;
 }
 function render(){
  for(const link of document.querySelectorAll('[data-tool-destination]')){
   link.hidden=!state.local&&!state.remote;link.href=state.local?'/center':'/console#tools';
  }
  for(const host of document.querySelectorAll('[data-navigation]')){
   const brand=element('a',null,'brand');brand.href='/console#dashboard';
   const mark=element('b','VA /'),name=element('span','车辆自主系统');name.append(element('small','统一控制台'));brand.append(mark,name);
   const nav=element('nav');nav.setAttribute('aria-label','主导航');
   function link(item,index){const a=element('a');a.href=item.href;a.dataset.navId=item.id;
    if(location.pathname==='/console'&&(remoteViews.has(item.id)||item.id==='dashboard'))a.dataset.view=item.id;
    a.append(element('span',String(index+1).padStart(2,'0')),document.createTextNode(item.label),element('small',item.description));return a;
   }
   state.items.forEach((item,index)=>nav.append(link(item,index)));
   const more=element('details',null,'nav-advanced'),advanced=element('nav');advanced.setAttribute('aria-label','高级导航');
   state.advanced.forEach((item,index)=>advanced.append(link(item,state.items.length+index)));
   more.open=state.advanced.some(item=>active(item.id));more.append(element('summary','高级功能'),advanced);
   const footer=element('footer');footer.append(element('span',null,'dot'),document.createTextNode(state.local?'本机控制台':'车辆自主系统'),element('small','工具启停与车辆控制分别管理'));
   host.replaceChildren(brand,element('p','工作台','nav-label'),nav,more,footer);
  }
  highlight();
 }
 const ready=window.VAFAuth.ready.then(async session=>{
  if(!session)return null;
  try{state=await window.VAFAuth.api('/api/ui/navigation');render();canonical();return state;}
  catch(error){for(const host of document.querySelectorAll('[data-navigation]')){
   const message=element('p','导航暂时不可用，请刷新页面。'),retry=element('button','重新加载');retry.onclick=()=>location.reload();host.replaceChildren(message,retry);
  }return null;}
 });
 window.addEventListener('hashchange',()=>{canonical();highlight();});
 return {ready,get state(){return state;}};
})();
