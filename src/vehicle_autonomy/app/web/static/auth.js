'use strict';
// Only the server holds the management key. Pages share an HttpOnly cookie.
window.VAFAuth=(()=>{
 let session=null,control='',redirecting=false;
 const channel=typeof BroadcastChannel==='function'?new BroadcastChannel('vaf-auth'):null;
 const next=()=>location.pathname+location.search+location.hash;
 function lost(){
  session=null;control='';window.dispatchEvent(new Event('vaf:auth-lost'));
  if(!redirecting&&location.pathname!=='/login'){redirecting=true;location.replace('/login?next='+encodeURIComponent(next()));}
 }
 if(channel)channel.onmessage=e=>{if(e.data==='logout')lost();};
 async function restore(){
  const r=await fetch('/api/auth/session',{credentials:'same-origin',cache:'no-store'});
  if(!r.ok){if(location.pathname!=='/login')lost();return null;}
  const data=await r.json();session=data.result;return session;
 }
 const ready=restore();
 async function api(path,payload){
  await ready;if(!session)throw Error('请先登录');
  const headers={};const options={credentials:'same-origin',cache:'no-store',headers,signal:AbortSignal.timeout(5000)};
  if(payload!==undefined){Object.assign(headers,{'Content-Type':'application/json','X-VAF-CSRF':session.csrf,'X-VAF-Request-ID':crypto.randomUUID()});options.method='POST';options.body=JSON.stringify(payload);}
  if(control)headers['X-VAF-Control']=control;
  const r=await fetch(path,options);const value=await r.json();
  if(r.status===401){lost();throw Error('登录已失效，请重新登录');}
  if(!r.ok||!value.ok)throw Error(value.error||'请求失败');return value.result;
 }
 async function logout(){
  await api('/api/auth/logout',{});if(channel)channel.postMessage('logout');lost();
 }
 document.addEventListener('DOMContentLoaded',()=>{
  for(const button of document.querySelectorAll('[data-logout]'))button.onclick=()=>logout().catch(lost);
 });
 return {ready,api,logout,get session(){return session;},get control(){return control;},set control(value){control=value||'';},lost};
})();
