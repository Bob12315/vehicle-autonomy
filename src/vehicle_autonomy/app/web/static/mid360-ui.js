'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let binding = null, pending = false, request = 0;
  let slamPending = false;
  $('enable-mid360-lio').onchange = () => { if ($('enable-mid360-lio').checked) $('enable-mid360').checked = true; };
  $('enable-mid360').onchange = () => { if (!$('enable-mid360').checked) $('enable-mid360-lio').checked = false; };
  function show(state) {
    $('mid360-summary').textContent = `实时数据：${state.online ? '在线' : state.live_closed ? '仿真已结束' : '未就绪'} · 回放：${state.replay_source || '未运行'} · RViz：${state.rviz_source || '未打开'} · ${state.namespace} · Domain ${JSON.stringify(state.domains)}`;
    $('mid360-status').textContent = JSON.stringify(state, null, 2);
    $('slam-panel').hidden = state.backend !== 'livox-gz-sliced-pattern-v1';
    if (!$('slam-panel').hidden && !slamPending) slamInvoke('status').catch(e => { $('slam-summary').textContent = e.message; });
    const select = $('mid360-bag'), previous = select.value;
    select.replaceChildren();
    for (const bag of state.bags || []) {
      if (!bag.complete) continue;
      const option = document.createElement('option');
      option.value = bag.id; option.textContent = bag.id;
      select.append(option);
    }
    if ([...select.options].some(o => o.value === previous)) select.value = previous;
    for (const button of document.querySelectorAll('[data-mid360]')) {
      const action = button.dataset.mid360;
      button.disabled = pending || (action === 'record_start' && (!state.online || !!state.recording)) ||
        (action === 'record_stop' && !state.recording) || (['replay_start','replay_once'].includes(action) && !select.value) ||
        (['sensor_start','fault_on','fault_off'].includes(action) && state.live_closed);
    }
  }
  async function slamInvoke(action) {
    if (!binding) return;
    const epoch = binding.id + binding.vehicle_id;
    const payload = {...binding, action, source: $('mid360-source').value};
    if (action === 'save') payload.name = $('slam-map-name').value;
    if (['load','relocalize'].includes(action)) payload.map_id = $('slam-map-id').value;
    if (action === 'relocalize') payload.seed = ['x','y','z','yaw'].map(k => Number($('reloc-' + k).value));
    const result = await window.VAFAuth.api('/api/simulation/slam', payload);
    if (!binding || epoch !== binding.id + binding.vehicle_id) return;
    $('slam-status').textContent = JSON.stringify(result, null, 2);
    if (action === 'maps') {
      const select = $('slam-map-id'), old = select.value;
      select.replaceChildren();
      for (const map of result.maps) {
        const option = document.createElement('option');
        option.value = map.id; option.textContent = `${map.name} · ${map.vehicle} · ${map.points} 点 · ${map.saved_at}`;
        select.append(option);
      }
      if ([...select.options].some(o => o.value === old)) select.value = old;
    }
    if (action === 'status') {
      const map = result.state?.map;
      const mapping = map?.error || (map ? `${map.points} 点 · ${map.paused ? '累计已暂停' : '累计中'}` : '等待地图');
      const source = {live: '实时仿真', replay: '录制回放'}[result.source] || '未选择来源';
      const relocation = result.relocalization?.online ? '匹配有效（只读）' : result.relocalization?.state ? '未获得有效匹配（查看诊断）' : '未启动地图匹配';
      $('slam-summary').textContent = `SLAM：${result.online ? '在线' : result.running ? '等待有效定位' : '已停止'} · ${source} · ${result.error ? '定位暂不可用（查看诊断）' : '局部里程计，未作全局对齐'} · 地图：${mapping} · 回环：${result.global_consistency} · 重定位：${relocation}`;
    }
    return result;
  }
  for (const button of document.querySelectorAll('[data-slam]')) button.onclick = async () => {
    if (slamPending) return;
    slamPending = true;
    for (const item of document.querySelectorAll('[data-slam]')) item.disabled = true;
    try { await slamInvoke(button.dataset.slam); if (['save','load'].includes(button.dataset.slam)) await slamInvoke('maps'); }
    catch (e) { $('slam-summary').textContent = e.message; }
    finally {
      slamPending = false;
      for (const item of document.querySelectorAll('[data-slam]')) item.disabled = false;
    }
  };
  async function invoke(action) {
    if (!binding) return;
    const epoch = binding.id + binding.vehicle_id, serial = ++request;
    const payload = {...binding, action, source: $('mid360-source').value};
    if (['replay_start','replay_once'].includes(action)) payload.bag_id = $('mid360-bag').value;
    const state = await window.VAFAuth.api('/api/simulation/mid360', payload);
    if (binding && epoch === binding.id + binding.vehicle_id && serial === request) show(state);
  }
  document.addEventListener('vaf:simulation-selection', event => {
    const {session, vehicle} = event.detail;
    const enabled = !!vehicle?.sensor_activation?.mid360?.enabled;
    $('mid360-panel').hidden = !enabled;
    const next = enabled ? {id: session.id, vehicle_id: vehicle.id} : null;
    if (!next || !binding || next.vehicle_id !== binding.vehicle_id) {
      request++; $('mid360-status').textContent = ''; $('mid360-bag').replaceChildren();
    }
    binding = next;
    if (binding && !pending) invoke('status').catch(e => { $('mid360-summary').textContent = e.message; });
  });
  for (const button of document.querySelectorAll('[data-mid360]')) button.onclick = async () => {
    if (pending) return;
    pending = true;
    for (const item of document.querySelectorAll('[data-mid360]')) item.disabled = true;
    try { await invoke(button.dataset.mid360); }
    catch (e) { $('mid360-summary').textContent = e.message; }
    finally { pending = false; if (binding) invoke('status').catch(() => {}); }
  };
})();
