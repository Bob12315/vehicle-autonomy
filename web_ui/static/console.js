'use strict';
const $ = id => document.getElementById(id);
let token = '', state = null, proposal = null, active = false;
const logs = [];
// Full clouds/maps belong to ROS visualizers; keep the operator view bounded.
const json = value => JSON.stringify(value, (key, item) => key === 'preview_xyz' ? undefined : item, 2);
function log(text) {
  logs.unshift(new Date().toLocaleTimeString() + ' ' + text);
  $('logs').textContent = logs.slice(0, 100).join('\n');
}
async function api(path, payload) {
  const headers = {'Authorization': 'Bearer ' + token};
  const options = {headers};
  if (payload !== undefined) {
    Object.assign(headers, {'Content-Type': 'application/json', 'X-VAF-CSRF': token,
      'X-VAF-Request-ID': crypto.randomUUID()});
    options.method = 'POST'; options.body = JSON.stringify(payload);
  }
  const response = await fetch('/api/' + path, options);
  const value = await response.json();
  if (!value.ok) throw new Error(value.error || '请求失败');
  return value.result;
}
async function action(fn) {
  try { $('error').textContent = ''; await fn(); }
  catch (e) { $('error').textContent = e.message; log(e.message); }
}
function showSummary(s) {
  const items = {'运行状态': s.state, '车辆连接': s.connected ? '在线' : '离线 / 未接入',
    '飞控模式': s.vehicle?.mode ?? '未知',
    '武装状态': s.vehicle?.armed === true ? 'ARMED' : s.vehicle?.armed === false ? 'Disarmed' : '未知',
    '系统 / Action SEND': String(s.system_send) + ' / ' + String(s.action_send),
    '物理停车': s.physical_stop ?? '未由此界面确认'};
  $('summary').replaceChildren();
  for (const [name, value] of Object.entries(items)) {
    const d = document.createElement('div'); d.className = 'stat';
    d.append(document.createTextNode(name));
    const b = document.createElement('b'); b.textContent = value;
    d.append(b); $('summary').append(d);
  }
  const readonly = s.mode === 'hardware_readonly';
  $('start').disabled = readonly || !$('missions').value;
  $('start').textContent = readonly ? '实车只读 · 任务未授权' : '启动所选任务';
  if (readonly) $('approve').disabled = true;
  $('task').textContent = json(s.task ?? {result: '无活动任务'});
  const lidar = s.lidar;
  $('ros-status').textContent = json({
    lidar: lidar ? {online: lidar.online, frame: lidar.frame, points: lidar.points,
      age_ms: lidar.age_ns === undefined ? null : lidar.age_ns / 1e6,
      skipped_cloud_versions: lidar.dropped_clouds, reason: lidar.reason} : '未配置',
    mapping: s.mapping ?? '未配置', localization: s.localization ?? '未准入',
    visualization: 'RViz2；默认 ROS 限定本机，SSH 网页隧道不转发 DDS'});
  $('diagnostics').textContent = json({telemetry: s.telemetry, localization: s.localization,
    slam_candidate: s.slam_localization_candidate, lidar: s.lidar, mapping: s.mapping,
    errors: s.errors ?? s.error});
  $('raw').textContent = json(s);
  $('camera-health').textContent = json(s.camera ?? s.sensor ?? {online: false, reason: '未配置摄像头'});
  if (!s.camera?.online) $('camera').removeAttribute('src');
}
$('connect').onclick = () => action(async () => {
  token = $('token').value; $('token').value = '';
  state = await api('status');
  const missions = await api('catalog'); $('missions').replaceChildren();
  for (const mission of missions) {
    const option = document.createElement('option'); option.value = option.textContent = mission;
    $('missions').append(option);
  }
  if (!missions.length) {
    const option = document.createElement('option'); option.value = '';
    option.textContent = '暂无已注册的可执行任务'; $('missions').append(option);
  }
  active = true; $('connection').textContent = '已认证 · Application API';
  showSummary(state); log('认证连接成功');
});
$('missions').onchange = () => { if (state) showSummary(state); };
$('start').onclick = () => action(async () => log(json(await api('start', {
  mission: $('missions').value, expected_session: state.session_id}))));
$('cancel').onclick = () => action(async () => log('软件停止请求：' + json(await api('cancel', {}))));
async function propose(path) {
  proposal = await api(path, {text: $('intent').value});
  $('proposal').textContent = json(proposal);
  $('approve').disabled = proposal.decision !== 'propose' || proposal.preflight?.eligible === false || state?.mode === 'hardware_readonly';
  $('human').checked = false;
}
$('propose').onclick = () => action(() => propose('propose'));
$('design').onclick = () => action(() => propose('design'));
$('approve').onclick = () => action(async () => {
  if (!$('human').checked) throw Error('必须人工检查并勾选确认');
  const value = await api(proposal.kind === 'design' ? 'design/approve' : 'approve', {id: proposal.id, human_approved: true});
  $('approve').disabled = true; log('提案结果：' + json(value));
});
async function refresh() {
  if (!active) return;
  try {
    state = await api('status'); showSummary(state);
    $('connection').textContent = '已认证 · Application API';
    if (state.logs) $('logs').textContent = state.logs.map(e => JSON.stringify(e)).slice(-30).join('\n') + '\n' + logs.slice(0, 20).join('\n');
  } catch (e) { $('connection').textContent = 'Application 离线'; $('error').textContent = e.message; }
}
async function camera() {
  if (!active || !state?.camera?.online) return;
  try {
    const frame = await api('camera'); $('camera').src = 'data:' + frame.mime + ';base64,' + frame.base64;
  } catch (e) { $('camera').removeAttribute('src'); }
}
setInterval(refresh, 1500); setInterval(camera, 400);
$('reports').onclick = () => action(async () => { $('report-text').textContent = (await api('reports')).text; });
