/* ============================================================
   SAP CPI Copilot — panel.js
   Complete application layer for the extension
   ============================================================ */

'use strict';

// ---- State ----
const state = {
  token: sessionStorage.getItem('cpi_token') || '',
  backend: localStorage.getItem('cpi_backend') || 'http://127.0.0.1:8000',
  principal: null,
  connected: false,
  currentView: 'v-agent',
  packages: [],
  agentMode: 'auto',
  wizard: {
    step: 1,
    planId: null,
    planResult: null,
    compileResult: null,
  },
  b2b: { compileResult: null },
  msg: { result: null, pattern: 'jms-retry' },
  tpl: { templates: [], selected: null },
};

// ---- DOM helpers ----
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const show = (el) => { if (el) el.hidden = false; };
const hide = (el) => { if (el) el.hidden = true; };

// ---- API ----
async function api(path, opts = {}) {
  const url = `${state.backend}${path}`;
  const headers = { 'Content-Type': 'application/json' };
  if (state.token) headers['Authorization'] = `Bearer ${state.token}`;
  const res = await fetch(url, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
  if (res.status === 401) { disconnect(); throw new Error('Unauthorized'); }
  if (res.status === 403) throw new Error('Forbidden');
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${txt}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

// ---- Notices ----
function showAlert(type, msg) {
  const el = $('#conn-notice');
  if (!el) return;
  const prefix = type === 'error' ? '✕ ' : type === 'success' ? '✓ ' : '';
  el.innerHTML = `<div class="alert alert-${type}">${prefix}${escapeHtml(msg)}</div>`;
}

// ---- Connection ----
function updateConnectionUI() {
  const dot = $('#conn-dot');
  const text = $('#conn-text');
  if (state.connected) {
    dot.className = 'dot on';
    text.textContent = state.principal?.tenant_name || 'Connected';
  } else {
    dot.className = 'dot';
    text.textContent = 'Offline';
  }
}

async function connect() {
  const backend = $('#set-backend').value.trim() || state.backend;
  const token = $('#set-token').value.trim();
  if (!token) { showAlert('error', 'Enter an access token.'); return; }
  state.backend = backend;
  state.token = token;
  localStorage.setItem('cpi_backend', backend);
  sessionStorage.setItem('cpi_token', token);
  $('#connect-btn').disabled = true;
  $('#connect-btn').textContent = 'Connecting…';
  try {
    const me = await api('/v1/me');
    state.principal = me;
    state.connected = true;
    showAlert('success', `Connected to ${me.tenant_name} (${me.environment})`);
    updateConnectionUI();
    await loadAll();
  } catch (e) {
    state.connected = false;
    showAlert('error', `Connection failed: ${e.message}`);
  } finally {
    $('#connect-btn').disabled = false;
    $('#connect-btn').textContent = 'Connect →';
  }
}

function disconnect() {
  state.token = '';
  state.principal = null;
  state.connected = false;
  state.packages = [];
  sessionStorage.removeItem('cpi_token');
  updateConnectionUI();
  showAlert('info', 'Disconnected.');
}

async function loadAll() {
  if (!state.connected) return;
  await loadPackages();
  loadTemplates();
}

// ---- Navigation ----
function navigate(view) {
  state.currentView = view;
  $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $$('.view').forEach(v => v.classList.remove('active'));
  const section = $(`#${view}`);
  if (section) { section.classList.add('active'); section.scrollTop = 0; }
  const titles = {
    'v-agent': 'iFlow Agent', 'v-b2b': 'B2B / TPM', 'v-apis': 'APIs',
    'v-messaging': 'Messaging', 'v-templates': 'Templates',
    'v-inventory': 'Packages & iFlows', 'v-activity': 'Activity',
    'v-connections': 'Connections', 'v-settings': 'Settings',
  };
  $('#view-title').textContent = titles[view] || view;
}

// ---- Wizard ----
function showWizardStep(n) {
  state.wizard.step = n;
  $$('.wizard-panel').forEach(p => p.classList.toggle('visible', +p.dataset.step === n));
  const bars = $$('#wizard .steps');
  bars.forEach(bar => {
    const items = bar.querySelectorAll('.step');
    items.forEach((s, i) => s.classList.toggle('active', i < n));
  });
}

// ---- Analyze ----
async function analyzeScenario() {
  const scenario = $('#agent-scenario').value.trim();
  if (!scenario) { showAlert('error', 'Describe your integration scenario.'); return; }
  const pkg = $('#agent-pkg').value || undefined;
  const pattern = $('#agent-pattern').value;

  navigate('v-agent');
  showWizardStep(2);
  $('#plan-loading').hidden = false;
  hide($('#plan-result'));

  try {
    const result = await api('/v1/designs/propose', {
      method: 'POST', body: JSON.stringify({ description: scenario, pattern, package_id: pkg }),
    });
    state.wizard.planResult = result;
    state.wizard.planId = result.id || result.plan_id;
    renderPlan(result);
  } catch (e) {
    $('#plan-loading').hidden = true;
    show($('#plan-result'));
    showAlert('error', `Analysis failed: ${e.message}`);
  }
}

function renderPlan(result) {
  $('#plan-loading').hidden = true;
  show($('#plan-result'));
  $('#plan-title').textContent = result.title || 'Integration Plan';
  $('#plan-summary').textContent = result.summary || '';

  if (result.requirements?.length) { show($('#plan-reqs')); $('#plan-reqs-list').innerHTML = result.requirements.map(r => `<li>${escapeHtml(r)}</li>`).join(''); }
  else hide($('#plan-reqs'));

  if (result.sub_flows?.length || result.architecture?.length) {
    show($('#plan-arch'));
    const flows = result.sub_flows || result.architecture || [];
    $('#plan-subflows').innerHTML = flows.map((f, i) => `
      <div class="subflow-card"><div class="subflow-header"><span class="subflow-num">${i + 1}</span><span class="subflow-name">${escapeHtml(f.name || f.id || 'Flow ' + (i + 1))}</span><span class="tag ${f.type === 'trigger' ? 'tag-copper' : f.type === 'process' ? 'tag-steel' : 'tag-steel'}">${escapeHtml(f.type || 'process')}</span></div>
      <div class="subflow-desc">${escapeHtml(f.description || f.summary || '')}</div>
      ${f.inputs?.length ? '<div class="subflow-meta"><span class="tag tag-steel">In: ' + f.inputs.length + '</span></div>' : ''}${f.outputs?.length ? '<div class="subflow-meta"><span class="tag tag-teal">Out: ' + f.outputs.length + '</span></div>' : ''}</div>`).join('');
  } else hide($('#plan-arch'));

  if (result.blockers?.length) { show($('#plan-blockers')); $('#plan-blockers-list').innerHTML = result.blockers.map(b => `<li>${escapeHtml(b)}</li>`).join(''); }
  else hide($('#plan-blockers'));

  if (result.questions?.length) { show($('#plan-questions')); $('#plan-questions-list').innerHTML = result.questions.map(q => `<div style="padding:8px 0;border-bottom:1px solid var(--border);font-size:12px;">${escapeHtml(q)}</div>`).join(''); }
  else hide($('#plan-questions'));

  if (result.assumptions?.length) { show($('#plan-assumptions')); $('#plan-assumptions-list').innerHTML = result.assumptions.map(a => `<li>${escapeHtml(a)}</li>`).join(''); }
  else hide($('#plan-assumptions'));

  const st = $('#plan-status');
  if (result.blockers?.length) { st.className = 'pill pill-red'; st.textContent = 'Blocked'; }
  else if (result.questions?.length) { st.className = 'pill pill-amber'; st.textContent = 'Needs info'; }
  else { st.className = 'pill pill-teal'; st.textContent = 'Ready'; }
}

// ---- Build ----
async function buildFromPlan() {
  if (!state.wizard.planResult) { showAlert('error', 'No plan available.'); return; }
  navigate('v-agent');
  showWizardStep(3);
  $('#build-loading').hidden = false;
  hide($('#build-result'));

  try {
    const planId = state.wizard.planId || state.wizard.planResult.id || state.wizard.planResult.plan_id;
    let result;
    try {
      result = await api('/v1/designs/compile', {
        method: 'POST', body: JSON.stringify({ plan_id: planId, description: $('#agent-scenario').value, package_id: $('#agent-pkg').value || undefined }),
      });
    } catch {
      result = await api('/v1/scenarios/compile', {
        method: 'POST', body: JSON.stringify({ description: $('#agent-scenario').value, pattern: $('#agent-pattern').value, package_id: $('#agent-pkg').value || undefined }),
      });
    }
    state.wizard.compileResult = result;
    renderBuild(result);
  } catch (e) {
    $('#build-loading').hidden = true;
    show($('#build-result'));
    $('#build-title').textContent = 'Build issue';
    $('#build-desc').textContent = e.message;
    showAlert('error', `Build failed: ${e.message}`);
  }
}

function renderBuild(result) {
  $('#build-loading').hidden = true;
  show($('#build-result'));
  $('#build-title').textContent = 'Build Complete';
  $('#build-desc').textContent = 'iFlow compiled. Review before deploying.';
  const flows = result.sub_flows || result.flows || result.bpmn || [];
  const el = $('#build-subflows');
  if (flows.length) {
    el.innerHTML = flows.map((f, i) => `
      <div class="subflow-card"><div class="subflow-header"><span class="subflow-num">${i + 1}</span><span class="subflow-name">${escapeHtml(f.name || f.id || 'Sub-flow ' + (i + 1))}</span><span class="tag tag-teal">COMPILED</span></div>
      <div style="background:var(--surface-2);border-radius:4px;padding:10px;font-size:11px;font-family:var(--font-mono);max-height:150px;overflow-y:auto;white-space:pre-wrap;color:var(--text-dim);margin-left:30px;">${escapeHtml(JSON.stringify(f, null, 2))}</div></div>`).join('');
  } else {
    el.innerHTML = `<pre class="code-block">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
  }
}

// ---- Review ----
function showReview() {
  navigate('v-agent');
  showWizardStep(4);
  const result = state.wizard.compileResult;
  if (!result) return;
  $('#review-status').textContent = 'Ready';
  hide($('#review-warning'));
  const flows = result.sub_flows || result.flows || result.bpmn || [];
  const diagram = $('#review-diagram');
  if (flows.length) {
    diagram.innerHTML = flows.map((f, i) => {
      const type = i === 0 ? 'trigger' : i === flows.length - 1 ? 'output' : 'process';
      const icon = type === 'trigger' ? '▶' : type === 'output' ? '■' : '◇';
      const parts = [];
      if (i > 0) parts.push(`<span class="arrow">→</span>`);
      parts.push(`<span class="node ${type}">${icon} ${escapeHtml(f.name || f.id || '')}</span>`);
      return parts.join('');
    }).join('');
  } else { diagram.innerHTML = '<span class="text-muted text-xs">No diagram available.</span>'; }
  show($('#review-diagram-section'));

  if (result.config || result.configuration) { show($('#review-config')); $('#review-config-content').textContent = JSON.stringify(result.config || result.configuration, null, 2); }
  if (result.bundle || result.zip || result.files) { show($('#review-bundle')); $('#review-bundle-content').textContent = JSON.stringify(result.bundle || result.zip || result.files, null, 2); }
  if (result.sample_input || result.samples?.input) { show($('#review-samples')); $('#review-input').textContent = JSON.stringify(result.sample_input || result.samples.input, null, 2); $('#review-output').textContent = JSON.stringify(result.sample_output || result.samples.output, null, 2); }
}

// ---- Deploy ----
async function deployFlow() {
  const result = state.wizard.compileResult;
  if (!result) return;
  const modal = $('#deploy-output');
  show(modal);
  modal.scrollIntoView({ behavior: 'smooth' });
  const statusEl = $('#deploy-status');
  const descEl = $('#deploy-desc');
  const timelineEl = $('#deploy-timeline');
  statusEl.className = 'pill pill-steel';
  statusEl.textContent = 'Deploying…';
  descEl.textContent = 'Uploading iFlow to SAP CPI tenant.';
  timelineEl.innerHTML = `<div class="t-item"><span class="t-dot" style="background:var(--steel);"></span><div class="t-content"><p class="t-title">Uploading iFlow</p><p class="t-time">Just now</p></div></div>`;
  try {
    const deployResult = await api('/v1/runs', {
      method: 'POST', body: JSON.stringify({
        action: 'upload_deploy',
        goal: `Deploy ${result.id || result.artifact_id || 'GeneratedFlow'}`,
        package_id: $('#agent-pkg').value,
        artifact_id: result.id || result.artifact_id || 'GeneratedFlow',
        version: $('#agent-version')?.value || 'active',
      }),
    });
    const runId = deployResult.run_id || deployResult.id;
    if (runId) {
      const run = await pollRun(runId);
      statusEl.className = 'pill pill-teal';
      statusEl.textContent = 'Deployed';
      descEl.textContent = `Run ${runId} completed.`;
      timelineEl.innerHTML += `<div class="t-item"><span class="t-dot" style="background:var(--teal);"></span><div class="t-content"><p class="t-title">Deployment complete</p><p class="t-time">${run.status || 'Success'}</p></div></div>`;
      showAlert('success', `iFlow deployed successfully. Run ID: ${runId}`);
    } else {
      statusEl.className = 'pill pill-teal';
      statusEl.textContent = 'Queued';
      descEl.textContent = 'Deployment request accepted.';
    }
  } catch (e) {
    statusEl.className = 'pill pill-red';
    statusEl.textContent = 'Failed';
    descEl.textContent = e.message;
    timelineEl.innerHTML += `<div class="t-item"><span class="t-dot" style="background:var(--red);"></span><div class="t-content"><p class="t-title">Deployment failed</p><p class="t-time">${escapeHtml(e.message)}</p></div></div>`;
    showAlert('error', `Deployment failed: ${e.message}`);
  }
}

async function pollRun(runId, maxAttempts = 20) {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const run = await api(`/v1/runs/${runId}`);
      if (run.status && ['completed', 'deployed', 'success', 'failed', 'error'].includes(run.status)) return run;
    } catch { /* ignore transient */ }
    await sleep(2000);
  }
  return { id: runId, status: 'unknown' };
}

// ---- B2B ----
async function proposeB2B() {
  const body = {
    package_id: $('#b2b-pkg').value || undefined,
    partner_id: $('#b2b-partner').value.trim(),
    standard: $('#b2b-standard').value,
    agreement_profile: $('#b2b-agreement').value.trim(),
    receiver_port: $('#b2b-receiver').value.trim(),
  };
  if (!body.partner_id) { showAlert('error', 'Enter a Partner ID.'); return; }
  try {
    const result = await api('/v1/b2b/propose', { method: 'POST', body: JSON.stringify(body) });
    state.b2b.compileResult = result;
    show($('#b2b-result'));
    $('#b2b-result-title').textContent = `B2B: ${body.partner_id}`;
    $('#b2b-result-desc').textContent = `${body.standard} · ${body.agreement_profile || 'default agreement'}`;
    $('#b2b-result-content').textContent = JSON.stringify(result, null, 2);
  } catch (e) { showAlert('error', `B2B propose failed: ${e.message}`); }
}

async function compileB2B() {
  if (!state.b2b.compileResult) { showAlert('error', 'Propose a B2B design first.'); return; }
  try {
    const result = await api('/v1/b2b/compile', { method: 'POST', body: JSON.stringify(state.b2b.compileResult) });
    $('#b2b-result-content').textContent = JSON.stringify(result, null, 2);
    showAlert('success', 'B2B design compiled.');
  } catch (e) { showAlert('error', `B2B compile failed: ${e.message}`); }
}

// ---- APIs ----
async function buildAPI() {
  const body = {
    package_id: $('#api-pkg').value || undefined,
    name: $('#api-name').value.trim(),
    base_path: $('#api-path').value.trim(),
    method: $('#api-method').value,
    format: $('#api-format').value,
  };
  if (!body.name) { showAlert('error', 'Enter an API name.'); return; }
  try {
    const result = await api('/v1/designs/api/compile', { method: 'POST', body: JSON.stringify(body) });
    show($('#api-result'));
    $('#api-result-desc').textContent = `${body.name} · ${body.method} ${body.base_path}`;
    $('#api-result-content').textContent = JSON.stringify(result, null, 2);
  } catch (e) { showAlert('error', `API build failed: ${e.message}`); }
}

// ---- Messaging ----
async function buildMsg() {
  const pattern = state.msg.pattern;
  const body = {
    pattern,
    package_id: $('#msg-pkg').value || undefined,
    jms_url: $('#msg-jms-url').value.trim(),
    queue: $('#msg-queue').value.trim(),
  };
  if (!body.jms_url && !body.queue) {
    body.description = pattern === 'jms-retry'
      ? 'Build JMS retry pattern with exponential backoff, dead letter queue, and monitoring.'
      : 'Build Solace event mesh with guaranteed delivery, topic hierarchy, and replay logging.';
  }
  try {
    const result = await api('/v1/designs/messaging/compile', { method: 'POST', body: JSON.stringify(body) });
    state.msg.result = result;
    show($('#msg-result'));
    $('#msg-result-desc').textContent = `${pattern === 'jms-retry' ? 'JMS Retry' : 'Solace'} pattern compiled`;
    $('#msg-result-content').textContent = JSON.stringify(result, null, 2);
  } catch (e) { showAlert('error', `Messaging build failed: ${e.message}`); }
}

// ---- Templates ----
async function loadTemplates() {
  try {
    const data = await api('/v1/templates');
    state.tpl.templates = data.templates || [];
    renderTemplates();
  } catch (e) {
    console.error('loadTemplates', e);
    $('#tpl-list').innerHTML = `<div class="alert alert-error">${escapeHtml(e.message)}</div>`;
  }
}

function renderTemplates() {
  const el = $('#tpl-list');
  if (!state.tpl.templates.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-desc">No templates available.</div></div>';
    return;
  }
  el.innerHTML = `<div class="board">${state.tpl.templates.map(t => `
    <div><div class="col-head"><span class="dot deployed"></span>${escapeHtml(t.category || 'Template')}</div>
    <div class="card-item c-deployed" data-tpl="${escapeHtml(t.id)}">
      <span class="tag tag-copper">${escapeHtml(t.complexity || '')}</span>
      <p>${escapeHtml(t.name || t.id)}</p>
      <p class="card-desc" style="font-size:11px;margin:4px 0 0;">${escapeHtml(t.description || '')}</p>
    </div></div>`).join('')}</div>`;
  $$('[data-tpl]', el).forEach(card => {
    card.addEventListener('click', () => selectTemplate(card.dataset.tpl));
  });
}

async function selectTemplate(tplId) {
  try {
    const tpl = await api(`/v1/templates/${encodeURIComponent(tplId)}`);
    state.tpl.selected = tpl;
    $('#tpl-title').textContent = tpl.name || tplId;
    $('#tpl-desc').textContent = tpl.description || '';
    const form = $('#tpl-form');
    form.innerHTML = (tpl.parameters || []).map(p => `
      <div class="field">
        <label class="label" for="tpl-param-${escapeHtml(p.name)}">${escapeHtml(p.label || p.name)}</label>
        <input class="input" data-p="${escapeHtml(p.name)}" value="${escapeHtml(p.default || '')}" placeholder="${escapeHtml(p.hint || '')}">
      </div>`).join('');
    hide($('#tpl-list'));
    show($('#tpl-detail'));
  } catch (e) { showAlert('error', e.message); }
}

// ---- Packages ----
async function loadPackages() {
  try {
    state.packages = await api('/v1/packages');
    const selects = ['#agent-pkg', '#b2b-pkg', '#api-pkg', '#msg-pkg'];
    selects.forEach(sel => {
      const el = $(sel);
      if (!el) return;
      el.innerHTML = '<option value="">Select package</option>' +
        state.packages.map(p => `<option value="${escapeHtml(p.Id)}">${escapeHtml(p.Id)} — ${escapeHtml(p.Name)}</option>`).join('');
    });
    renderPackages();
  } catch (e) { console.error('loadPackages', e); }
}

function renderPackages() {
  const el = $('#pkgs-list');
  if (!state.packages.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">◫</div><div class="empty-title">No packages</div><div class="empty-desc">Connect to load packages.</div></div>';
    return;
  }
  el.innerHTML = `<div class="board">${state.packages.map(p => `
    <div><div class="card-item c-deployed"><span class="tag tag-steel">Package</span><p>${escapeHtml(p.Id)}</p>
    <p class="card-desc" style="font-size:11px;margin:4px 0 0;">${escapeHtml(p.Name || '')}</p></div></div>`).join('')}</div>`;
}

// ---- Runs ----
async function loadRuns() {
  try {
    const runs = await api('/v1/runs');
    const el = $('#runs-list');
    if (!runs?.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-icon">◷</div><div class="empty-title">No activity</div></div>';
      return;
    }
    el.innerHTML = `<div class="timeline">${runs.map(r => `
      <div class="t-item"><span class="t-dot" style="background:var(--steel);"></span>
      <div class="t-content"><p class="t-title">${escapeHtml(r.id)}</p>
      <p class="t-time">${new Date(r.created).toLocaleString()}</p></div></div>`).join('')}</div>`;
  } catch (e) { console.error(e); }
}

// ---- Connections ----
async function loadConn() {
  try {
    const caps = await api('/v1/capabilities');
    const diag = await api('/v1/diagnostics');
    const el = $('#conn-output');
    el.textContent = JSON.stringify({ capabilities: caps, diagnostics: diag }, null, 2);
    el.style.display = 'block';
  } catch (e) {
    $('#conn-output').textContent = `Error: ${e.message}`;
    $('#conn-output').style.display = 'block';
  }
}

// ---- Examples ----
const EXAMPLES = {
  invoice: 'Receive HTTPS JSON with an invoices array. Validate invoice_id and amount, calculate tax at 8%, enrich with customer data, route disputed invoices for manual review, then return processed invoices.',
  inventory: 'Receive inventory updates via HTTPS POST. Validate product_id and stock levels. Trigger alerts when stock falls below threshold. Aggregate changes per warehouse.',
  order: 'Receive order messages from external system. Map to SAP IDoc format, validate business rules (credit check, duplicates), split large orders into batches, route rush orders for priority processing.',
  b2b: 'Set up B2B integration with Walmart. Use EDIFACT ORDERS D96A standard. Configure partner parameters for interchange control. Map incoming ORDERS to internal order format.',
};

// ---- Utility ----
function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ---- Downloads ----
function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadCurrentZip() {
  const result = state.wizard.compileResult || state.b2b.compileResult;
  if (!result) { showAlert('error', 'No compiled result to download.'); return; }
  downloadJson(`${result.id || result.artifact_id || 'design'}.json`, result);
}

// ---- Modal ----
function showModal(title, body, actions = []) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = body;
  $('#modal-footer').innerHTML = actions.map(a =>
    `<button class="btn ${a.cls || 'btn-outline'}" data-action="${a.id}">${a.label}</button>`
  ).join('');
  show($('#modal-overlay'));
  $('#modal-overlay').addEventListener('click', function overlayCleanup(e) {
    if (e.target === $('#modal-overlay')) {
      hide($('#modal-overlay'));
      $('#modal-overlay').removeEventListener('click', overlayCleanup);
    }
  });
  $$('#modal-footer button').forEach(b => {
    b.addEventListener('click', () => {
      hide($('#modal-overlay'));
      const action = actions.find(a => a.id === b.dataset.action);
      if (action?.handler) action.handler();
    });
  });
}

function confirmProceed(msg) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (val) => {
      if (settled) return;
      settled = true;
      hide($('#modal-overlay'));
      resolve(val);
    };
    showModal('Confirm', `<p>${escapeHtml(msg)}</p>`, [
      { id: 'cancel', label: 'Cancel', cls: 'btn-outline', handler: () => done(false) },
      { id: 'proceed', label: 'Proceed', cls: 'btn-primary', handler: () => done(true) },
    ]);
    $('#modal-close').addEventListener('click', () => done(false), { once: true });
  });
}

// ---- Auto-connect if token present ----
async function autoConnect() {
  if (!state.token) return;
  state.backend = localStorage.getItem('cpi_backend') || 'http://127.0.0.1:8000';
  $('#set-backend').value = state.backend;
  $('#set-token').value = state.token;
  try {
    const me = await api('/v1/me');
    state.principal = me;
    state.connected = true;
    updateConnectionUI();
    await loadAll();
  } catch { /* silent */ }
}

// ---- Event Binding ----
function bindEvents() {
  // Navigation — sidebar .nav-item[data-view]
  $$('.nav-item[data-view]').forEach(btn => {
    btn.addEventListener('click', () => navigate(btn.dataset.view));
  });

  // Connection
  $('#connect-btn')?.addEventListener('click', connect);
  $('#disconnect-btn')?.addEventListener('click', () => {
    disconnect();
    showAlert('info', 'Disconnected.');
  });

  // New task
  $('#new-task-btn')?.addEventListener('click', () => {
    state.wizard = { step: 1, planId: null, planResult: null, compileResult: null };
    $('#agent-scenario').value = '';
    hide($('#deploy-output'));
    navigate('v-agent');
    showWizardStep(1);
  });

  // Agent mode selector
  $$('#mode-auto, #mode-guided').forEach(card => {
    card.addEventListener('click', () => {
      state.agentMode = card.id === 'mode-auto' ? 'auto' : 'guided';
      $$('#mode-auto, #mode-guided').forEach(c => c.classList.remove('active'));
      card.classList.add('active');
    });
  });

  // Example buttons
  $$('[data-example]').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.example;
      if (EXAMPLES[key]) $('#agent-scenario').value = EXAMPLES[key];
    });
  });

  // Agent: Analyze
  $('#analyze-btn')?.addEventListener('click', analyzeScenario);

  // Plan: actions
  $('#plan-back')?.addEventListener('click', () => showWizardStep(1));
  $('#plan-build')?.addEventListener('click', () => {
    if (state.agentMode === 'guided') {
      confirmProceed('Build this iFlow design?').then(ok => { if (ok) buildFromPlan(); });
    } else {
      buildFromPlan();
    }
  });

  // Build: actions
  $('#build-back')?.addEventListener('click', () => showWizardStep(2));
  $('#build-download')?.addEventListener('click', downloadCurrentZip);
  $('#build-review')?.addEventListener('click', showReview);

  // Review: actions
  $('#review-back')?.addEventListener('click', () => showWizardStep(3));
  $('#review-deploy')?.addEventListener('click', deployFlow);
  $('#review-download')?.addEventListener('click', downloadCurrentZip);

  // B2B
  $('#b2b-propose')?.addEventListener('click', proposeB2B);
  $('#b2b-compile')?.addEventListener('click', compileB2B);
  $('#b2b-download')?.addEventListener('click', () => {
    if (state.b2b.compileResult) downloadJson('b2b-design.json', state.b2b.compileResult);
  });

  // APIs
  $('#api-build')?.addEventListener('click', buildAPI);
  $('#api-download')?.addEventListener('click', () => {
    const el = $('#api-result-content');
    if (el) downloadJson('api-design.json', JSON.parse(el.textContent));
  });

  // Messaging
  $$('#msg-jms, #msg-solace').forEach(card => {
    card.addEventListener('click', () => {
      state.msg.pattern = card.id === 'msg-jms' ? 'jms-retry' : 'solace';
      $$('#msg-jms, #msg-solace').forEach(c => c.classList.remove('active'));
      card.classList.add('active');
    });
  });
  $('#msg-build')?.addEventListener('click', buildMsg);
  $('#msg-download')?.addEventListener('click', () => {
    const el = $('#msg-result-content');
    if (el) downloadJson('messaging-pattern.json', JSON.parse(el.textContent));
  });

  // Templates
  $('#refresh-tpl')?.addEventListener('click', loadTemplates);
  $('#tpl-back')?.addEventListener('click', () => {
    hide($('#tpl-detail'));
    show($('#tpl-list'));
  });
  $('#tpl-build')?.addEventListener('click', () => {
    const params = {};
    $$('[data-p]').forEach(el => { params[el.dataset.p] = el.value; });
    const tpl = state.tpl.selected;
    showAlert('info', `Building from template "${tpl?.name || ''}" with parameters: ${JSON.stringify(params)}`);
  });

  // Inventory
  $('#refresh-pkgs')?.addEventListener('click', loadPackages);

  // Activity
  $('#refresh-runs')?.addEventListener('click', loadRuns);

  // Connections
  $('#check-conn')?.addEventListener('click', loadConn);
  $('#diagnose')?.addEventListener('click', async () => {
    try {
      const data = await api('/v1/diagnostics');
      $('#conn-output').textContent = JSON.stringify(data, null, 2);
      $('#conn-output').style.display = 'block';
    } catch (e) { showAlert('error', e.message); }
  });

  // Settings — populate with current values
  $('#set-backend').value = state.backend;
  $('#set-token').value = state.token;
}

// ---- Init ----
function init() {
  bindEvents();
  updateConnectionUI();
  autoConnect();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
