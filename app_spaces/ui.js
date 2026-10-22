(function () {

  'use strict';

  const root = document.getElementById('app-spaces');

  if (!root || root.dataset.mounted) return;

  root.dataset.mounted = 'true';
  if(!window.APP_SPACES_DEMO&&location.pathname.endsWith('/static/app_spaces/index.html')){const prefix=location.pathname.slice(0,-'/static/app_spaces/index.html'.length);history.replaceState(null,'',prefix+'/app-spaces');}

  const $ = s => root.querySelector(s);

  const closeForNavigation = () => {};

  let csrf=sessionStorage.getItem('app-spaces-csrf')||'';

  let authResolve;

  const authentication=csrf?Promise.resolve():new Promise(resolve=>{authResolve=resolve;});

  const receiveBootstrap=e=>{if(e.origin===location.origin&&e.source===window.opener&&e.data?.type==='APP_SPACES_BOOTSTRAP'&&typeof e.data.csrf==='string'){csrf=e.data.csrf;sessionStorage.setItem('app-spaces-csrf',csrf);authResolve?.();}};

  window.addEventListener('message',receiveBootstrap);

  window.opener?.postMessage({type:'APP_SPACES_READY'},location.origin);

  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  const icons={more:'<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false" fill="currentColor"><circle cx="8" cy="3" r="1.4"/><circle cx="8" cy="8" r="1.4"/><circle cx="8" cy="13" r="1.4"/></svg>',close:'<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.5"><path d="m4 4 8 8M12 4l-8 8"/></svg>',right:'<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.5"><path d="m6 3 5 5-5 5"/></svg>',down:'<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.5"><path d="m3 6 5 5 5-5"/></svg>'};
  const state = {namespaces: [], services: [], warnings: [], selected: new Set(), collapsed: new Set(['extra']), active: null, config: null, tab: 'Overview', candidates: [], busy: false};

  let alive = true;

  function notify(message, error) { const el = $('#toast'); el.textContent = message; el.style.background = error ? '#683c41' : '#2d4b3d'; el.classList.remove('hidden'); clearTimeout(state.toastTimer); state.toastTimer = setTimeout(() => el.classList.add('hidden'), 6500); }

  async function request(operation, data = {}) {

    if (window.APP_SPACES_DEMO && window.appSpacesDemoRequest) return window.appSpacesDemoRequest(operation, data);

    if(!csrf){let timer;try{await Promise.race([authentication,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Open App Spaces from aaPanel to authenticate this tab.')),15000);})]);}finally{clearTimeout(timer);}}

    const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),['create_service','action'].includes(operation)?660000:operation==='metrics'?12000:45000);

    try {

      const response=await fetch('/plugin?action=a&name=app_spaces&s=api',{method:'POST',credentials:'same-origin',cache:'no-store',signal:controller.signal,headers:{'Content-Type':'application/x-www-form-urlencoded','x-http-token':csrf},body:new URLSearchParams({payload:JSON.stringify({operation,request_id:Array.from(crypto.getRandomValues(new Uint8Array(24)),b=>b.toString(16).padStart(2,'0')).join(''),...data})})});

      if(!response.ok)throw Error('Panel request failed. Reopen App Spaces from aaPanel if your session expired.');

      const result=await response.json();if(!result?.status)throw Error(result?.msg||'Request failed');return result.data;

    } finally {clearTimeout(timeout);}

  }

  function prettyBytes(n) { if (n == null) return '\u2014'; return n > 1048576 ? (n / 1048576).toFixed(0) + ' MB' : (n / 1024).toFixed(0) + ' KB'; }

  function age(n) { if (n == null) return '\u2014'; return n > 86400 ? Math.floor(n / 86400) + ' days' : n > 3600 ? Math.floor(n / 3600) + ' hours' : Math.floor(n / 60) + ' min'; }

  function endpoint(e) { return `${e.host.includes(':') ? '[' + e.host + ']' : e.host}:${e.port}${e.container_port ? ' \u2192 ' + e.container_port : ''}/${e.protocol}`; }

  function statusClass(s) { return s === 'Running' ? 'running' : s === 'Failed' ? 'failed' : 'stopped'; }

  function filtered() { const query = $('#search').value.toLowerCase(); return state.services.filter(s => ($('#nsFilter').value === 'all' || s.namespace === $('#nsFilter').value) && ($('#runtime').value === 'all' || s.runtime === $('#runtime').value) && ($('#state').value === 'all' || s.state === $('#state').value) && [s.name, s.source, s.namespace, ...s.proxies.flatMap(p => p.domains)].join(' ').toLowerCase().includes(query)); }

  function filters() { const current = $('#nsFilter').value; $('#nsFilter').innerHTML = '<option value="all">All namespaces</option>' + state.namespaces.map(n => `<option value="${esc(n.slug)}">${esc(n.slug)}</option>`).join(''); if ([...$('#nsFilter').options].some(x => x.value === current)) $('#nsFilter').value = current; }

  function render() {

    const list = filtered();

    $('#rows').innerHTML = [...state.namespaces].sort((a,b)=>(a.slug==='extra')-(b.slug==='extra')||a.slug.localeCompare(b.slug)).filter(n => $('#nsFilter').value === 'all' || n.slug === $('#nsFilter').value).map(n => {

      const services = list.filter(s => s.namespace === n.slug);

      if (!services.length && ($('#search').value || $('#runtime').value !== 'all' || $('#state').value !== 'all')) return '';

      return `<tr class="namespace"><td colspan="9"><div class="nshead"><button class="collapse" data-collapse="${esc(n.slug)}" aria-label="Toggle ${esc(n.slug)}" aria-expanded="${!state.collapsed.has(n.slug)}">${state.collapsed.has(n.slug) ? icons.right : icons.down}</button><span class="hint">Namespace:</span><span class="nsname">${esc(n.slug)}</span><span class="tag">${esc(n.environment || 'App')}</span><small>${esc(n.description)}</small><span class="nsright">${services.length} services \u00b7 ${services.filter(s => s.state === 'Running').length} running</span><button ${n.virtual ? 'disabled' : ''} data-delete-ns="${esc(n.slug)}" class="collapse" aria-label="Delete empty namespace ${esc(n.slug)}">${icons.close}</button></div></td></tr>` + (state.collapsed.has(n.slug) ? '' : services.map(s => `<tr>

      <td><input type="checkbox" data-check="${esc(s.id)}" ${!s.capabilities.lifecycle ? 'disabled' : ''} aria-label="Select ${esc(s.name)}" ${state.selected.has(s.id) ? 'checked' : ''}></td>

      <td><span class="status ${statusClass(s.state)}">${esc(s.state)}</span>${s.error ? '<div class="sub">Details unavailable</div>' : ''}</td>

      <td><button class="service" data-open="${esc(s.id)}">${esc(s.name)}</button><div class="mono" title="${esc(s.source)}">${esc(s.source)}</div>${s.instances.length > 1 ? `<div class="sub">${s.instances.length} instances</div>` : ''}</td>

      <td><span class="runtime ${s.runtime}">${s.runtime === 'docker' ? 'Docker' : 'systemd'}</span></td>

      <td>${s.endpoints.map(e => `<div class="mono">${esc(endpoint(e))}</div>`).join('') || '<span class="unmapped">No known host listener</span>'}</td>

      <td>${s.proxies.length ? `<button class="proxy" data-proxy="${esc(s.id)}">${esc(s.proxies[0].domains[0] || s.proxies[0].project)} \u2197</button><div class="sub">${esc(s.proxies[0].project)}${s.proxies.length > 1 ? ' \u00b7 +' + (s.proxies.length - 1) + ' routes' : ''}</div>` : '<span class="unmapped">No proxy matched</span>'}</td>

      <td class="metrics" data-metric="${esc(s.id)}">${s.cpu == null ? '\u2014' : esc(s.cpu) + '%'} / ${prettyBytes(s.memory)}</td><td class="metrics">${age(s.uptime)}</td>

      <td><button class="more" data-open="${esc(s.id)}" aria-label="Details for ${esc(s.name)}">${icons.more}</button></td></tr>`).join('') || '') + (!services.length && !state.collapsed.has(n.slug) ? '<tr><td colspan="9" class="empty">No registered workloads. Use Discover services to add existing services.</td></tr>' : '');

    }).join('') || '<tr><td colspan="9" class="empty">No matching workloads. Create a namespace, then discover services to register.</td></tr>';

    $('#nsCount').textContent = state.namespaces.filter(n=>!n.virtual).length; $('#svcCount').textContent = state.services.length; $('#runCount').textContent = state.services.filter(s => s.state === 'Running').length; $('#attention').textContent = state.services.filter(s => ['Failed', 'Unavailable'].includes(s.state)).length;

    $('#proxyCount').textContent = new Set(state.services.flatMap(s => s.proxies.map(p => p.file))).size;

    $('#countLabel').textContent = `${list.length} of ${state.services.length} services`;

    $('#selected').textContent = state.selected.size ? `(${state.selected.size})` : '';

    $('#bulk').disabled = state.busy || !state.selected.size;

    const visible = list.filter(s => !state.collapsed.has(s.namespace)); $('#checkall').checked = visible.length > 0 && visible.filter(s=>s.capabilities.lifecycle).every(s => state.selected.has(s.id)); $('#checkall').indeterminate = visible.some(s => state.selected.has(s.id)) && !$('#checkall').checked;

    $('#warnings').innerHTML = state.warnings.length ? `<details><summary>${state.warnings.length} proxy discovery notes \u00b7 existing services are unaffected</summary><ul>${state.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details>` : ''; $('#warnings').classList.toggle('hidden', !state.warnings.length); if(typeof paintMetrics==='function')paintMetrics();

  }

  let refreshing=false;

  async function refresh() { if (state.busy||refreshing) return; refreshing=true; try { $('#refresh').disabled = true; const data = await request('inventory'); if (!alive) return; state.namespaces = data.namespaces; state.services = data.services; state.warnings = data.warnings; state.selected.forEach(id => { if (!state.services.some(s => s.id === id)) state.selected.delete(id); }); filters(); render(); pollMetrics(); $('#updated').textContent = 'Updated ' + new Date(data.at).toLocaleTimeString(); } catch (e) { notify(e.message, true); $('#rows').innerHTML = '<tr><td colspan="9" class="empty">Inventory unavailable. Refresh after checking the panel session and plugin installation.</td></tr>'; } finally { refreshing=false; $('#refresh').disabled = false; } }

  async function open(id, tab = 'Overview') { state.active = state.services.find(s => s.id === id); if (!state.active) return; if(state.active.unregistered){state.registering=state.active;$('#registerTitle').textContent='Register '+state.active.name;$('#regLabel').value=state.active.name;$('#regNs').replaceChildren(...state.namespaces.filter(n=>!n.virtual).map(n=>new Option(n.slug,n.slug)));$('#regConfig').checked=false;$('#regConfig').disabled=!state.active.config_supported;$('#regLifecycle').checked=false;$('#registerDialog').showModal();return;} state.tab = tab; state.config = null; $('#detail').showModal(); await detail(); }

  async function detail(reveal = false) {

    const s = state.active; const requestedTab = state.tab;

    root.appSpacesCodeEditor?.dispose();

    $('#detail').classList.toggle('configuration-open',['Configuration','Logs'].includes(requestedTab));

    $('#detail').classList.toggle('logs-open',requestedTab==='Logs');

    if(requestedTab!=='Configuration')$('#detail').classList.remove('editor-expanded');

    $('#dnamespace').textContent = s.namespace + ' / ' + s.runtime; $('#dtitle').textContent = s.name;

    $('#tabs').innerHTML = ['Overview', 'Environment', 'Configuration', 'Logs', 'Proxy'].map(t => `<button data-tab="${t}" class="${state.tab === t ? 'active' : ''}">${t}</button>`).join('');

    $('#dcontent').innerHTML = '<p>Loading\u2026</p>'; $('#dactions').innerHTML = '';

    try {

      let html = '';

      if (requestedTab === 'Overview') html = `<div class="kv"><span>Status</span><span class="status ${statusClass(s.state)}">${esc(s.state)}</span><span>Native identity</span><span style="overflow-wrap:anywhere">${esc(s.native)}</span><span>Namespace</span><select id="moveNs">${state.namespaces.filter(n=>!n.virtual).map(n => `<option ${n.slug === s.namespace ? 'selected' : ''}>${esc(n.slug)}</option>`).join('')}</select><span>Configuration</span><span>${s.capabilities.config ? 'Local unit editing enabled' : 'Read-only / externally owned'}</span><span>Lifecycle</span><span>${s.capabilities.lifecycle ? 'Enabled' : 'Read-only registration'}</span></div>${s.instances.length ? '<h3>Instances</h3>' + s.instances.map(i => `<div class="kv"><span>${esc(i.name)}</span><span>${esc(i.state)} \u00b7 ${esc(i.health || 'No health check')}</span></div>`).join('') : ''}${s.error ? `<p>${esc(s.error)}</p>` : ''}<button id="unregister">Unregister workload</button><p class="hint">Unregistering removes this listing only. The service/container remains intact.</p>`;

      if (requestedTab === 'Proxy') html = s.proxies.length ? s.proxies.map(p => `<div class="notice"><strong>${esc(p.project)}</strong><div>${esc(p.domains.join(', '))}</div><div class="mono">${esc(p.location)} \u2192 ${esc(p.target)}</div><div class="hint">${esc(p.confidence)} \u00b7 ${esc(p.origin)}</div></div>`).join('') + '<p class="hint">Matches are inferred from local ports. Routing and SSL remain managed by aaPanel. Included configuration and dynamic upstreams may be unresolved.</p>' : '<p>No local proxy route matched this workload. Internal services may intentionally have no public domain.</p>';

      if (requestedTab === 'Environment') { const data = await request('environment', {id:s.id, reveal}); html = `<p style="margin-bottom:15px">${esc(data.note)}</p><button id="revealEnv">${reveal ? 'Hide values' : 'Reveal values'}</button>` + Object.entries(data.instances).map(([instance, env]) => `<h3>${esc(instance)}</h3>${env.map(v => `<div class="envrow"><input aria-label="Variable name" readonly value="${esc(v.key)}"><input aria-label="Variable value" readonly value="${esc(v.value)}"></div>`).join('')}`).join('') + '<p class="hint">For a registered local systemd unit, edit variables in Configuration. Docker environment updates must be applied by its deployment owner and require recreation.</p>'; }

      if (requestedTab === 'Logs') { const data = await request('logs', {id:s.id, lines:150}); html = `<p class="hint">${esc(data.note)}</p><pre>${esc(data.text)}</pre><button id="reloadLogs">Refresh logs</button>`; }

      if (requestedTab === 'Configuration') {

        if (!s.capabilities.config) html = '<p>Configuration editing is not enabled for this workload. Local systemd units can be registered with configuration permission. Docker source editing and adoption are not supported in this release.</p>';

        else { const data = await request('configuration', {id:s.id, reveal}); state.config = data; html = `<p class="mono" title="${esc(data.path)}">${esc(data.path)}</p><p class="hint">${esc(data.note)} ${data.dropins ? 'Drop-ins: ' + esc(data.dropins) : ''}</p><button id="revealConfig">${data.editable ? 'Hide sensitive configuration' : 'Reveal & edit configuration'}</button><textarea id="rawConfig" spellcheck="false" aria-label="Service configuration" ${data.editable ? '' : 'readonly'}>${esc(data.content)}</textarea><p class="hint">Preview validates the unit and checks for concurrent changes. Apply backs up the original, reloads systemd and restarts this service.</p>`; }

      }

      if (state.active !== s || state.tab !== requestedTab || !$('#detail').open) return;

      $('#dcontent').innerHTML = html;

      if(requestedTab==='Configuration'&&$('#rawConfig'))root.appSpacesCodeEditor?.mount($('#rawConfig'));

      $('#dactions').innerHTML = (s.capabilities.lifecycle ? `<button data-action="${s.state === 'Running' ? 'stop' : 'start'}">${s.state === 'Running' ? 'Stop' : 'Start'}</button><button data-action="restart">Restart</button>` : '') + (requestedTab === 'Configuration' && state.config && state.config.editable ? '<button class="primary" id="previewConfig">Validate & preview</button>' : '');

      const envButton = $('#revealEnv'); if (envButton) envButton.onclick = () => detail(!reveal);

      const configButton = $('#revealConfig'); if (configButton) configButton.onclick = () => { if (!reveal && !confirm('Reveal this unit file? It may contain production credentials.')) return; detail(!reveal); };

      const logsButton = $('#reloadLogs'); if (logsButton) logsButton.onclick = () => detail();

    } catch (e) { if (state.active === s && state.tab === requestedTab) $('#dcontent').textContent = e.message; }

  }

  async function action(ids, verb) { if (state.busy) return; if (!confirm(`${verb.toUpperCase()} ${ids.length} registered workload(s)? This affects real running applications.`)) return; state.busy = true; render(); const results = []; try { for (const id of ids) { try { const response = await request('action', {id, verb, confirmed:true}); if (response.ok === false) throw new Error('One or more container instances failed'); results.push({id, ok:true}); } catch(e) { results.push({id, ok:false, error:e.message}); } } } finally { state.busy = false; } state.selected.clear(); if ($('#detail').open) $('#detail').close(); await refresh(); notify(results.every(r => r.ok) ? `${verb} completed for ${results.length} workload(s).` : results.filter(r => !r.ok).map(r => `${r.id}: ${r.error}`).join('; '), results.some(r => !r.ok)); }

  async function discover() {

    $('#discovery').showModal(); $('#candidates').textContent = 'Discovering systemd services and Docker containers\u2026';

    try { const data = await request('discover'); state.candidates = data.services; $('#discoveryWarnings').textContent = data.warnings.join(' \u00b7 '); drawCandidates(); } catch(e) { $('#candidates').textContent = e.message; }

  }

  function drawCandidates() { const q = $('#candidateSearch').value.toLowerCase(); $('#candidates').innerHTML = state.candidates.map((s, i) => ({s,i})).filter(({s}) => [s.name,s.source,s.runtime].join(' ').toLowerCase().includes(q)).slice(0,150).map(({s,i}) => `<div class="candidate"><div><strong>${esc(s.name)}</strong> <span class="runtime">${esc(s.runtime)}</span><div class="mono" title="${esc(s.native)}">${esc(s.native)}</div><div class="sub">${esc(s.state)}</div></div><button data-register="${i}">Register</button></div>`).join('') || '<p>No unregistered workloads found.</p>'; }

  root.addEventListener('click', async e => {

    const b = e.target.closest('button'); if (!b) return;

    try {

      if (b.dataset.close) $(b.dataset.close).close();

      if (b.dataset.open) await open(b.dataset.open);

      if (b.dataset.proxy) await open(b.dataset.proxy, 'Proxy');

      if (b.dataset.tab) { state.tab = b.dataset.tab; state.config = null; await detail(); }

      if (b.dataset.collapse) { const n = b.dataset.collapse; state.collapsed.has(n) ? state.collapsed.delete(n) : state.collapsed.add(n); render(); }

      if (b.dataset.deleteNs) { if (confirm('Delete this empty namespace? Workloads are never deleted.')) { await request('namespaces', {namespace_operation:'delete', slug:b.dataset.deleteNs}); await refresh(); } }

      if (b.dataset.action) await action([state.active.id], b.dataset.action);

      if (b.id === 'bulk') await action([...state.selected], 'restart');

      if (b.id === 'refresh') await refresh();

      if (b.id === 'discover') await discover();

      if (b.id === 'newns') $('#create').showModal();

      if (b.id === 'previewConfig') { const data = await request('preview', {id:state.active.id, content:$('#rawConfig').value, revision:state.config.revision}); state.ticket = data.token; $('#configDiff').textContent = data.diff; $('#applyNote').textContent = data.notice; $('#applyDialog').showModal(); }

      if (b.id === 'applyConfig') { if (!confirm('Apply this configuration and restart the service?')) return; b.disabled = true; try { const data = await request('apply', {id:state.active.id, token:state.ticket, confirmed:true}); $('#applyDialog').close(); $('#detail').close(); await refresh(); notify('Configuration applied. Backup: ' + data.backup); } finally { b.disabled = false; } }

      if (b.id === 'unregister') { const label = prompt('Type ' + state.active.name + ' to unregister. This will not stop or delete it.'); if (label != null) { await request('unregister', {id:state.active.id, confirmation:label}); $('#detail').close(); await refresh(); } }

      if (b.dataset.register != null) { const item = state.candidates[Number(b.dataset.register)]; state.registering = item; $('#registerTitle').textContent = 'Register ' + item.name; $('#regLabel').value = item.name; $('#regNs').innerHTML = state.namespaces.filter(n=>!n.virtual).map(n => `<option>${esc(n.slug)}</option>`).join(''); $('#regConfig').checked = false; $('#regConfig').disabled = !item.config_supported || item.runtime !== 'systemd'; $('#regLifecycle').checked = false; $('#registerDialog').showModal(); }

      if (b.id === 'audit') { const data = await request('audit'); $('#auditText').textContent = data.map(x => `${x.at}  ${x.operation}  ${x.target}  ${x.outcome}`).join('\n') || 'No recorded operations.'; $('#auditDialog').showModal(); }

      if (b.id === 'export') { const data = await request('export'); const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type:'application/json'})); const link = document.createElement('a'); link.href = url; link.download = 'app-spaces-registrations.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000); }

    } catch(e) { notify(e.message, true); }

  });

  $('#rows').addEventListener('change', e => { if (e.target.dataset.check) { const id=e.target.dataset.check; e.target.checked ? state.selected.add(id) : state.selected.delete(id); render(); } });

  $('#checkall').onchange = e => { filtered().filter(s => s.capabilities.lifecycle && !state.collapsed.has(s.namespace)).forEach(s => e.target.checked ? state.selected.add(s.id) : state.selected.delete(s.id)); render(); };

  ['search','nsFilter','runtime','state'].forEach(id => $('#'+id).addEventListener(id==='search'?'input':'change', render));

  $('#candidateSearch').oninput = drawCandidates;

  $('#dcontent').onchange = async e => { if (e.target.id !== 'moveNs') return; try { await request('move', {id:state.active.id, namespace:e.target.value}); state.active.namespace=e.target.value; await refresh(); } catch(err) { notify(err.message,true); } };

  $('#nsform').onsubmit = async e => { e.preventDefault(); try { await request('namespaces', {namespace_operation:'create',slug:$('#nsname').value,description:$('#nsdescription').value,environment:$('#nsenvironment').value}); $('#create').close(); $('#nsform').reset(); await refresh(); } catch(err) { notify(err.message,true); } };

  $('#registerForm').onsubmit = async e => { e.preventDefault(); if (!$('#regNs').value) return notify('Create a namespace first.', true); try { await request('register', {runtime:state.registering.runtime,native:state.registering.native,namespace:$('#regNs').value,label:$('#regLabel').value,lifecycle:$('#regLifecycle').checked,config:$('#regConfig').checked}); $('#registerDialog').close(); $('#discovery').close(); await refresh(); } catch(err) { notify(err.message,true); } };

  const observer = new MutationObserver(() => { if (!document.contains(root)) { alive=false; clearInterval(interval);clearTimeout(metricsTimer);window.removeEventListener('message',receiveBootstrap);document.removeEventListener('click',closeForNavigation,true); observer.disconnect(); } }); observer.observe(document.body,{childList:true,subtree:true});

  const interval = setInterval(() => { if (!root.querySelector('dialog[open]') && !document.hidden) refresh(); },30000);

  $('#demoLabel').classList.toggle('hidden', !window.APP_SPACES_DEMO);

  $('#detail').addEventListener('close',()=>{root.appSpacesCodeEditor?.dispose();state.config=null;$('#dcontent').replaceChildren();$('#detail').classList.remove('configuration-open','editor-expanded','logs-open');});

  root.appSpaces = {request, refresh, notify};

  let metricsTimer, metricsBusy=false;

  const latestMetrics=new Map();

  async function pollMetrics(){

    clearTimeout(metricsTimer);if(metricsBusy||!alive)return;

    if(document.hidden){metricsTimer=setTimeout(pollMetrics,5000);return;}

    metricsBusy=true;let failed=false;const started=performance.now();

    try{const data=await request('metrics');if(!alive)return;for(const metric of data.services){latestMetrics.set(metric.id,metric);const service=state.services.find(s=>s.id===metric.id);if(service)Object.assign(service,{cpu:metric.cpu,memory:metric.memory});}paintMetrics();$('#metricsUpdated').textContent='Metrics '+new Date(data.at*1000||Date.now()).toLocaleTimeString()+' \u00b7 every 5s';}

    catch(e){failed=true;$('#metricsUpdated').textContent='Metrics unavailable \u00b7 retrying';latestMetrics.clear();for(const service of state.services){service.cpu=null;service.memory=null;}for(const cell of root.querySelectorAll('[data-metric]')){cell.title='Metrics unavailable: '+e.message;cell.textContent='\u2014 / \u2014';}}

    finally{metricsBusy=false;if(alive)metricsTimer=setTimeout(pollMetrics,failed?10000:Math.max(1000,5000-(performance.now()-started)));}

  }

  function paintMetrics(){for(const cell of root.querySelectorAll('[data-metric]')){const m=latestMetrics.get(cell.dataset.metric);if(!m)continue;cell.textContent=(m.cpu==null?(m.status==='sampling'?'Sampling\u2026':'\u2014'):m.cpu.toFixed(1)+'%')+' / '+prettyBytes(m.memory);cell.title='CPU: 100% = one core. '+(m.status==='inactive'?'Service is inactive.':m.status==='unavailable'?'Counters unavailable.':'Live cgroup usage.');}}

  document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollMetrics();});

  refresh();

}());

