'use strict';
const form=document.querySelector('#login-form'),key=document.querySelector('#login-key'),error=document.querySelector('#login-error');
function destination(){let value=new URLSearchParams(location.search).get('next')||'/console';if(!value.includes('#'))value+=location.hash;return /^\/(?:console|control|studio)?(?:[?#]|$)/.test(value)&&!value.startsWith('//')?value:'/console';}
form.onsubmit=async e=>{
 e.preventDefault();error.textContent='';document.querySelector('#login-submit').disabled=true;
 try{
  const r=await fetch('/api/auth/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:key.value})});
  key.value='';const data=await r.json();if(!r.ok||!data.ok)throw Error(data.error||'登录失败');location.replace(destination());
 }catch(e){key.value='';error.textContent=e.message;document.querySelector('#login-submit').disabled=false;}
};
fetch('/api/auth/session',{credentials:'same-origin',cache:'no-store'}).then(r=>{if(r.ok)location.replace(destination());}).catch(()=>{});
