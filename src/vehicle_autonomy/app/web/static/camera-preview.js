'use strict';
(() => {
 const $=id=>document.getElementById(id);
 let image=$('camera-video');
 let target=null,camera=null,rows=[],generation=0,busy=false,streaming=false,health=null,observed=0,waitingUntil=0,streamStarted=0,disposed=false;
 function clear(message){image.hidden=true;image.removeAttribute('src');const empty=image.cloneNode(false);image.replaceWith(empty);image=empty;streaming=false;$('camera-empty').hidden=false;$('camera-empty').textContent=message;$('camera-fullscreen').disabled=true;$('camera-snapshot').disabled=true;}
 function select(value){if(value===target)return;target=value;camera=null;health=null;rows=[];generation++;waitingUntil=0;clear(value?'正在检查画面':'请先选择车辆');$('camera-source').replaceChildren(new Option('等待画面目录',''));$('camera-identity').textContent='';$('camera-source-info').textContent='';$('camera-state').textContent=value?'连接中':'未选择车辆';refresh();}
 function start(){if(!target||!camera||!health?.online||streaming||Date.now()<waitingUntil)return;streaming=true;streamStarted=performance.now();const view=image;image.onerror=()=>{if(view!==image)return;clear('视频流已中断，等待新帧');waitingUntil=Date.now()+700;};image.src='/api/cameras/'+encodeURIComponent(camera)+'/stream?target='+encodeURIComponent(target);}
 async function refresh(){
  if(busy||!target||disposed||document.hidden)return;busy=true;const expected=target,version=generation;
  try{
   const data=await window.VAF.call('/api/cameras?target='+encodeURIComponent(expected));
   if(expected!==target||version!==generation)return;
   rows=data.cameras;if(!rows.some(r=>r.camera_id===camera)){camera=rows.length===1?rows[0].camera_id:null;clear('等待新画面帧');}
   $('camera-source').replaceChildren(...(rows.length?[new Option('请选择画面',''),...rows.map(r=>new Option(r.display_name||(r.kind==='gazebo'?'原始摄像头画面 · '+r.slot:r.slot+' · '+r.kind),r.camera_id))]:[new Option('当前车辆无画面','')]));$('camera-source').value=camera||'';
   health=rows.find(r=>r.camera_id===camera);observed=performance.now();
   if(!health){clear(rows.length?'请选择当前车辆的画面':'当前车辆没有已绑定的画面');$('camera-state').textContent=rows.length?'待选择':'未配置';$('camera-health').textContent='只读视频，不申请控制权。';return;}
   const b=health.binding;$('camera-identity').textContent=`${health.camera_id} · target ${b.target} · ${b.world} / ${b.session} · epoch ${b.epoch}`;
   $('camera-state').textContent=health.online?'实时 · '+(health.kind==='recording'?'录像来源':'在线'):health.state+' · '+(health.reason||'不可用');
   const age=health.age_ns===null?'未知':(health.age_ns/1e6).toFixed(0)+' ms';
   $('camera-health').textContent=`第 ${health.sequence||'—'} 帧 · 接收 ${health.received_utc_ns?new Date(health.received_utc_ns/1e6).toLocaleTimeString():'未知'} · ${health.width||'—'} × ${health.height||'—'} · ${health.kind==='yolo'?'相机 ':''}${(health.fps||0).toFixed(1)} FPS · 延迟（主机帧年龄）${age}`;
   $('camera-source-info').textContent=(health.source||'')+' · '+(health.capture_clock||'采样时间未知');
   if(health.online){if(streaming&&performance.now()-streamStarted>55000)clear('更新视频连接');start();}else clear('画面不可用：'+(health.reason||'数据过期'));
  }catch(e){if(expected===target&&version===generation){health=null;clear('无法获取视频：'+e.message);$('camera-state').textContent='连接失败';}}
  finally{busy=false;}
 }
 $('camera-source').onchange=()=>{generation++;camera=$('camera-source').value;health=rows.find(r=>r.camera_id===camera);clear('正在切换画面');waitingUntil=0;$('camera-state').textContent='连接中';$('camera-health').textContent='等待新来源的首帧';start();refresh();};
 $('camera-fullscreen').onclick=()=>{$('camera-view').requestFullscreen?.().catch(()=>{});};
 $('camera-snapshot').onclick=async()=>{
  const expected=target,id=camera,version=generation;
  try{
   const response=await fetch('/api/cameras/'+encodeURIComponent(id)+'/snapshot?target='+encodeURIComponent(expected),{credentials:'same-origin',cache:'no-store'});
   if(!response.ok)throw Error('当前帧已失效');const blob=await response.blob();
   if(version!==generation||id!==camera||expected!==target)return;
   const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=id+'-'+response.headers.get('X-Frame-Sequence')+'.jpg';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){$('camera-health').textContent=e.message;}
 };
 setInterval(refresh,500);
 setInterval(()=>{if(streaming&&health?.online&&image.naturalWidth>0){image.hidden=false;$('camera-empty').hidden=true;$('camera-fullscreen').disabled=false;$('camera-snapshot').disabled=false;}if(health?.online&&health.age_ns/1e6+performance.now()-observed>1000){health.online=false;clear('图像已过期，等待新帧');$('camera-state').textContent='STALE';}},100);
 document.addEventListener('visibilitychange',()=>{clear(document.hidden?'页面已暂停预览':'等待新帧');if(!document.hidden)refresh();});
 window.addEventListener('pagehide',()=>{disposed=true;clear('页面已关闭');});
 window.addEventListener('pageshow',()=>{disposed=false;refresh();});
 window.addEventListener('vaf:auth-lost',()=>{health=null;clear('登录已失效');});
 window.VAFCamera={select};
})();
