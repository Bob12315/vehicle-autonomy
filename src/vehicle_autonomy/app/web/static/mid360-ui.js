'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let binding = null, pending = false, request = 0;
  function show(state) {
    $('mid360-summary').textContent = `实时数据：${state.online ? '在线' : state.live_closed ? '仿真已结束' : '未就绪'} · 回放：${state.replay_source || '未运行'} · RViz：${state.rviz_source || '未打开'} · ${state.namespace} · Domain ${JSON.stringify(state.domains)}`;
    $('mid360-status').textContent = JSON.stringify(state, null, 2);
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
        (action === 'record_stop' && !state.recording) || (action === 'replay_start' && !select.value) ||
        (['sensor_start','fault_on','fault_off'].includes(action) && state.live_closed);
    }
  }
  async function invoke(action) {
    if (!binding) return;
    const epoch = binding.id + binding.vehicle_id, serial = ++request;
    const payload = {...binding, action, source: $('mid360-source').value};
    if (action === 'replay_start') payload.bag_id = $('mid360-bag').value;
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
