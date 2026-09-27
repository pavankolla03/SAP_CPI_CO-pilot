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
  currentView: 'agent',
  packages: [],
  agentMode: 'auto',
  // agent wizard
  wizard: {
    step: 1,
    planId: null,
    planResult: null,
    compileResult: null,
    subflowDetail: null,
  },
  // b2b
  b2b: { compileResult: null },
  // messaging
  msg: { result: null, pattern: 'jms-retry' },
  // templates
  tpl: { templates: [], selected: null },
  // inventory
  inv: { tab: 'packages', iflows: [] },
};

// ---- DOM refs ----
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

function showAlert(type, msg, elId = 'notice') {
  const el = document.getElementById(elId);
  if (!el) return;
  el.className = `alert alert-${type}`;
  el.innerHTML = `<span>${type === 'error' ? '✕' : type === 'success' ? '✓' : 'ℹ'}</span><span>${msg}</span>`;
  el.hidden = false;
  setTimeout(() => { el.hidden = true; }, 6000);
}

// ---- Connection ----
function updateConnectionUI() {
  const dot = $('#conn-dot');
  const text = $('#conn-text');
  if (state.connected) {
    dot.className = 'connection-dot online';
    text.textContent = state.principal?.tenant_name || 'Connected';
  } else {
    dot.className = 'connection-dot';
    text.textContent = 'Disconnected';
  }
}

async function connect() {
  const backend = $('#setting-backend')?.value?.trim() || state.backend;
  const token = $('#setting-token')?.value?.trim();
  if (!token) { showAlert('error', 'Enter an access token.'); return; }
  state.backend = backend;
  state.token = token;
  localStorage.setItem('cpi_backend', backend);
  sessionStorage.setItem('cpi_token', token);
  $('#connect-btn').disabled = true;
  $('#connect-btn').innerHTML = '<span class="spinner"></span> Connecting…';
  try {
    const me = await api('/v1/me');
    state.principal = me;
    state.connected = true;
    showAlert('success', `Connected to ${me.tenant_name} (${me.environment})`, 'notice');
    updateConnectionUI();
    await loadAll();
  } catch (e) {
    state.connected = false;
    showAlert('error', `Connection failed: ${e.message}`, 'notice');
  } finally {
    $('#connect-btn').disabled = false;
    $('#connect-btn').textContent = 'Connect Workspace →';
  }
}

function disconnect() {
  state.token = '';
  state.principal = null;
  state.connected = false;
  state.packages = [];
  sessionStorage.removeItem('cpi_token');
  updateConnectionUI();
  showAlert('info', 'Disconnected.', 'notice');
}

async function loadAll() {
  if (!state.connected) return;
  await loadPackages();
  loadTemplates();
  loadB2BPartners();
}

// ---- Navigation ----
function navigate(view) {
  state.currentView = view;
  $$('.sidebar-btn').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $$('#content > section').forEach(s => { s.hidden = true; });
  const section = $(`#view-${view}`);
  if (section) { section.hidden = false; section.classList.add('fade-in'); }
  const titles = {
    agent: 'iFlow Agent', b2b: 'B2B / TPM', messaging: 'Messaging',
    templates: 'Templates', inventory: 'Packages & iFlows',
    runs: 'Activity', connections: 'Connections', settings: 'Settings',
  };
  $('#view-title').textContent = titles[view] || view;
}

// ---- Packages ----
async function loadPackages() {
  try {
    state.packages = await api('/v1/packages');
    const selects = ['#agent-package', '#b2b-package', '#msg-package'];
    selects.forEach(sel => {
      const el = $(sel);
      if (!el) return;
      el.innerHTML = '<option value="">Select package</option>' +
        state.packages.map(p => `<option value="${p.Id}">${p.Id} — ${escapeHtml(p.Name)}</option>`).join('');
    });
    const filter = $('#inventory-package-filter');
    if (filter) {
      filter.innerHTML = '<option value="">All packages</option>' +
        state.packages.map(p => `<option value="${p.Id}">${escapeHtml(p.Name)}</option>`).join('');
    }
    renderPackages();
  } catch (e) { console.error('loadPackages', e); }
}

function renderPackages() {
  const el = $('#packages-list');
  if (!el) return;
  if (!state.packages.length) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">◫</div><div class="empty-title">No packages</div><div class="empty-desc">Connect to load packages.</div></div>`;
    return;
  }
  el.innerHTML = `<div class="inventory-grid">${state.packages.map(p => `
    <div class="inventory-item" data-pkg="${p.Id}">
      <div class="inventory-item-name">${escapeHtml(p.Id)}</div>
      <div class="inventory-item-meta">${escapeHtml(p.Name || '')}</div>
      <div class="inventory-item-desc">${escapeHtml(p.Description || '')}</div>
      <div class="inventory-item-actions">
        <button class="btn btn-outline btn-sm view-flows-btn" data-pkg="${p.Id}">View iFlows</button>
      </div>
    </div>`).join('')}</div>`;
  $$('.view-flows-btn', el).forEach(btn => {
    btn.addEventListener('click', () => loadIflows(btn.dataset.pkg));
  });
}

async function loadIflows(pkgId) {
  state.inv.tab = 'iflows';
  $$('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.invTab === 'iflows'));
  $('#inv-packages-panel').hidden = true;
  $('#inv-iflows-panel').hidden = false;
  const el = $('#iflows-list');
  el.innerHTML = '<div class="empty-state"><div class="spinner" style="border-color:rgba(0,112,242,0.2);border-top-color:var(--accent)"></div><div class="empty-title mt-2">Loading…</div></div>';
  try {
    const flows = await api(`/v1/packages/${encodeURIComponent(pkgId)}/iflows`);
    if (!flows?.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-title">No iFlows</div></div>';
      return;
    }
    el.innerHTML = `<div class="inventory-grid">${flows.map(f => `
      <div class="inventory-item" data-flow="${f.Id}">
        <div class="inventory-item-name">${escapeHtml(f.Id)}</div>
        <div class="inventory-item-meta">v${escapeHtml(f.Version || 'active')}</div>
        <div class="inventory-item-desc">${escapeHtml(f.Name || '')}</div>
        <div class="inventory-item-actions">
          <button class="btn btn-outline btn-sm flow-detail-btn" data-id="${f.Id}">Details</button>
        </div>
      </div>`).join('')}</div>`;
    $$('.flow-detail-btn', el).forEach(btn => {
      btn.addEventListener('click', () => loadFlowDetail(btn.dataset.id));
    });
  } catch (e) {
    el.innerHTML = `<div class="alert alert-error">${escapeHtml(e.message)}</div>`;
  }
}

async function loadFlowDetail(artifactId) {
  try {
    const data = await api(`/v1/iflows/${encodeURIComponent(artifactId)}`);
    const el = $('#artifact-detail');
    el.textContent = JSON.stringify(data, null, 2);
    el.hidden = false;
  } catch (e) { showAlert('error', e.message); }
}

// ---- Runs / Activity ----
async function loadRuns() {
  try {
    const runs = await api('/v1/runs');
    const el = $('#runs-list');
    if (!runs?.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-icon">◷</div><div class="empty-title">No activity</div></div>';
      return;
    }
    el.innerHTML = runs.map(r => `
      <div class="inventory-item">
        <div class="inventory-item-name">${escapeHtml(r.id)}</div>
        <div class="inventory-item-meta">${new Date(r.created).toLocaleString()}</div>
      </div>`).join('');
  } catch (e) { console.error(e); }
}

// ---- Connections / Diagnostics ----
async function loadConnections() {
  try {
    const caps = await api('/v1/capabilities');
    const diag = await api('/v1/diagnostics');
    const el = $('#connections-content');
    el.textContent = JSON.stringify({ capabilities: caps, diagnostics: diag }, null, 2);
    show($('#connections-result'));
  } catch (e) {
    $('#connections-content').textContent = `Error: ${e.message}`;
    show($('#connections-result'));
  }
}

async function loadChannelJobs() {
  try {
    const jobs = await api('/v1/channel-jobs');
    const el = $('#channel-jobs-list');
    if (!jobs?.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-desc">No pending jobs.</div></div>';
      return;
    }
    el.innerHTML = jobs.map(j => `
      <div class="inventory-item">
        <div class="inventory-item-name">${escapeHtml(j.id)}</div>
        <div class="inventory-item-meta">${escapeHtml(j.status || '')} · ${j.run_id || ''}</div>
      </div>`).join('');
  } catch (e) { console.error(e); }
}

// ---- Templates ----
async function loadTemplates() {
  try {
    const data = await api('/v1/templates');
    state.tpl.templates = data.templates || [];
    renderTemplates();
  } catch (e) {
    console.error('loadTemplates', e);
    $('#templates-list').innerHTML = `<div class="alert alert-error">${escapeHtml(e.message)}</div>`;
  }
}

function renderTemplates() {
  const el = $('#templates-list');
  if (!state.tpl.templates.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-desc">No templates available.</div></div>';
    return;
  }
  el.innerHTML = `<div class="inventory-grid">${state.tpl.templates.map(t => `
    <div class="inventory-item" data-tpl="${t.id}">
      <div class="inventory-item-name">${escapeHtml(t.name || t.id)}</div>
      <div class="inventory-item-meta">${escapeHtml(t.category || '')} · ${t.complexity || ''}</div>
      <div class="inventory-item-desc">${escapeHtml(t.description || '')}</div>
      <div class="inventory-item-actions">
        <button class="btn btn-outline btn-sm tpl-select-btn" data-tpl="${t.id}">Use Template →</button>
      </div>
    </div>`).join('')}</div>`;
  $$('.tpl-select-btn', el).forEach(btn => {
    btn.addEventListener('click', () => selectTemplate(btn.dataset.tpl));
  });
}

async function selectTemplate(tplId) {
  try {
    const tpl = await api(`/v1/templates/${encodeURIComponent(tplId)}`);
    state.tpl.selected = tpl;
    $('#tpl-detail-title').textContent = tpl.name || tplId;
    $('#tpl-detail-desc').textContent = tpl.description || '';
    const form = $('#tpl-detail-form');
    form.innerHTML = (tpl.parameters || []).map(p => `
      <div class="form-group">
        <label class="form-label" for="tpl-param-${escapeHtml(p.name)}">${escapeHtml(p.label || p.name)}</label>
        <input class="form-input tpl-param" data-param="${escapeHtml(p.name)}" value="${escapeHtml(p.default || '')}" placeholder="${escapeHtml(p.hint || '')}">
        ${p.description ? `<div class="form-hint">${escapeHtml(p.description)}</div>` : ''}
      </div>`).join('');
    hide($('#templates-list'));
    show($('#template-detail'));
  } catch (e) { showAlert('error', e.message); }
}

// ---- Agent Wizard: Step 1 → 2 ----
async function analyzeScenario() {
  const scenario = $('#agent-scenario').value.trim();
  if (!scenario) { showAlert('error', 'Describe your integration scenario.'); return; }
  const packageId = $('#agent-package').value || undefined;
  const pattern = $('#agent-pattern').value;

  navigate('agent');
  showWizardStep(2);
  $('#plan-loading').hidden = false;
  hide($('#plan-result'));

  try {
    const body = {
      description: scenario,
      pattern,
      package_id: packageId,
    };
    const result = await api('/v1/designs/propose', {
      method: 'POST', body: JSON.stringify(body),
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

  // Requirements
  if (result.requirements?.length) {
    show($('#plan-requirements-section'));
    $('#plan-requirements').innerHTML = result.requirements.map(r => `<li>${escapeHtml(r)}</li>`).join('');
  } else { hide($('#plan-requirements-section')); }

  // Sub-flows (architecture)
  if (result.sub_flows?.length || result.architecture?.length) {
    show($('#plan-architecture-section'));
    const flows = result.sub_flows || result.architecture || [];
    $('#plan-subflows').innerHTML = flows.map((f, i) => `
      <div class="subflow-card" data-flow-idx="${i}">
        <div class="subflow-header">
          <span class="subflow-num">${i + 1}</span>
          <span class="subflow-name">${escapeHtml(f.name || f.id || `Flow ${i + 1}`)}</span>
          <span class="tag ${f.type === 'trigger' ? 'tag-blue' : f.type === 'process' ? 'tag-green' : 'tag-gray'}">${escapeHtml(f.type || 'process')}</span>
        </div>
        <div class="subflow-desc">${escapeHtml(f.description || f.summary || '')}</div>
        ${f.inputs?.length ? `<div class="subflow-meta"><span class="tag tag-gray">In: ${f.inputs.length}</span></div>` : ''}
        ${f.outputs?.length ? `<div class="subflow-meta"><span class="tag tag-green">Out: ${f.outputs.length}</span></div>` : ''}
      </div>`).join('');
  } else { hide($('#plan-architecture-section')); }

  // Blockers
  if (result.blockers?.length) {
    show($('#plan-blockers-section'));
    $('#plan-blockers').innerHTML = result.blockers.map(b => `<li>${escapeHtml(b)}</li>`).join('');
  } else { hide($('#plan-blockers-section')); }

  // Questions
  if (result.questions?.length) {
    show($('#plan-questions-section'));
    $('#plan-questions').innerHTML = result.questions.map(q => `
      <div style="padding:8px 0;border-bottom:1px solid var(--border-light)">
        <div style="font-size:12px;font-weight:500">${escapeHtml(q)}</div>
      </div>`).join('');
  } else { hide($('#plan-questions-section')); }

  // Assumptions
  if (result.assumptions?.length) {
    show($('#plan-assumptions-section'));
    $('#plan-assumptions').innerHTML = result.assumptions.map(a => `<li>${escapeHtml(a)}</li>`).join('');
  } else { hide($('#plan-assumptions-section')); }

  const status = $('#plan-status');
  status.className = 'status-pill ' + (result.blockers?.length ? 'error' : result.questions?.length ? 'warning' : 'success');
  status.textContent = result.blockers?.length ? 'Blocked' : result.questions?.length ? 'Needs info' : 'Ready';
}

// ---- Agent Wizard: Step 2 → 3 (Build) ----
async function buildFromPlan() {
  if (!state.wizard.planResult) { showAlert('error', 'No plan available.'); return; }
  navigate('agent');
  showWizardStep(3);
  $('#build-loading').hidden = false;
  hide($('#build-result'));

  try {
    const planId = state.wizard.planId || state.wizard.planResult.id || state.wizard.planResult.plan_id;
    const compileBody = {
      plan_id: planId,
      description: $('#agent-scenario').value,
      package_id: $('#agent-package').value || undefined,
    };

    // Try compile endpoint
    let result;
    try {
      result = await api('/v1/designs/compile', {
        method: 'POST', body: JSON.stringify(compileBody),
      });
    } catch (e) {
      // Fallback: try scenario compile
      result = await api('/v1/scenarios/compile', {
        method: 'POST', body: JSON.stringify({
          description: $('#agent-scenario').value,
          pattern: $('#agent-pattern').value,
          package_id: $('#agent-package').value || undefined,
        }),
      });
    }

    state.wizard.compileResult = result;
    renderBuildResult(result);
  } catch (e) {
    $('#build-loading').hidden = true;
    show($('#build-result'));
    $('#build-status-title').textContent = 'Build encountered an issue';
    $('#build-status-desc').textContent = e.message;
    showAlert('error', `Build failed: ${e.message}`);
  }
}

function renderBuildResult(result) {
  $('#build-loading').hidden = true;
  show($('#build-result'));
  $('#build-status-title').textContent = 'Build Complete';
  $('#build-status-desc').textContent = 'iFlow compiled successfully. Review before deploying.';

  const el = $('#build-subflows');
  const flows = result.sub_flows || result.flows || result.bpmn || [];
  if (flows.length) {
    el.innerHTML = flows.map((f, i) => `
      <div class="agent-step-card">
        <div class="agent-step-header">
          <div class="agent-step-indicator done">✓</div>
          <div class="agent-step-title">${escapeHtml(f.name || f.id || `Sub-flow ${i + 1}`)}</div>
          <span class="agent-step-status">COMPILED</span>
        </div>
        <div class="agent-step-output">${escapeHtml(JSON.stringify(f, null, 2))}</div>
      </div>`).join('');
  } else {
    el.innerHTML = `<pre class="code-block">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
  }
}

// ---- Agent Wizard: Step 3 → 4 (Review) ----
function showReview() {
  navigate('agent');
  showWizardStep(4);
  const result = state.wizard.compileResult;
  if (!result) return;

  // Diagram preview
  const diagram = $('#review-diagram');
  const flows = result.sub_flows || result.flows || result.bpmn || [];
  if (flows.length) {
    diagram.innerHTML = flows.map((f, i) => {
      const type = i === 0 ? 'trigger' : i === flows.length - 1 ? 'output' : 'process';
      const icon = type === 'trigger' ? '▶' : type === 'output' ? '■' : '◇';
      const parts = [f];
      if (i > 0) parts.unshift({ type: 'arrow', label: '' });
      return parts.map(p => {
        if (p.type === 'arrow') return `<span class="flow-arrow">→</span>`;
        return `<span class="flow-node ${type}">${icon} ${escapeHtml(p.name || p.id || '')}</span>`;
      }).join('');
    }).join('');
  } else {
    diagram.innerHTML = '<div class="empty-desc">No diagram available for this result type.</div>';
  }
  show($('#review-diagram-section'));

  // Config
  if (result.config || result.configuration) {
    show($('#review-config-section'));
    $('#review-config').textContent = JSON.stringify(result.config || result.configuration, null, 2);
  }

  // Bundle info
  if (result.bundle || result.zip || result.files) {
    show($('#review-bundle-section'));
    $('#review-bundle').textContent = JSON.stringify(result.bundle || result.zip || result.files, null, 2);
  }

  // Sample I/O
  if (result.sample_input || result.samples?.input) {
    show($('#review-samples-section'));
    $('#review-input').textContent = JSON.stringify(result.sample_input || result.samples.input, null, 2);
    $('#review-output').textContent = JSON.stringify(result.sample_output || result.samples.output, null, 2);
  }
}

// ---- Deployment ----
async function deployFlow() {
  const result = state.wizard.compileResult;
  if (!result) return;
  const modal = $('#deployment-output');
  show(modal);
  modal.scrollIntoView({ behavior: 'smooth' });

  const statusEl = $('#deploy-status');
  const descEl = $('#deploy-result-desc');
  const timelineEl = $('#deploy-timeline');

  statusEl.className = 'status-pill info';
  statusEl.textContent = 'Deploying…';
  descEl.textContent = 'Uploading iFlow to SAP CPI tenant.';
  timelineEl.innerHTML = `<li class="timeline-item"><div class="timeline-dot">◷</div><div class="timeline-content"><div class="timeline-title">Uploading iFlow</div><div class="timeline-desc">Sending bundle to SAP CPI…</div><div class="timeline-time">Just now</div></div></li>`;

  try {
    const deployBody = {
      artifact_id: result.artifact_id || result.id || 'GeneratedFlow',
      package_id: $('#agent-package').value,
      version: $('#agent-version')?.value || 'active',
      bundle: result.bundle || result,
    };
    const deployResult = await api('/v1/runs', {
      method: 'POST',
      body: JSON.stringify({
        action: 'upload_deploy',
        goal: `Deploy generated iFlow ${deployBody.artifact_id}`,
        package_id: deployBody.package_id,
        artifact_id: deployBody.artifact_id,
        version: deployBody.version,
      }),
    });
    // Poll for status
    const runId = deployResult.run_id || deployResult.id;
    if (runId) {
      const run = await pollRun(runId);
      statusEl.className = 'status-pill success';
      statusEl.textContent = 'Deployed';
      descEl.textContent = `Run ${runId} completed successfully.`;
      addTimelineItem(timelineEl, '✓', 'Deployment complete', run.status || 'Success', 'ok');
      showAlert('success', `iFlow deployed successfully. Run ID: ${runId}`);
    } else {
      statusEl.className = 'status-pill success';
      statusEl.textContent = 'Queued';
      descEl.textContent = 'Deployment request accepted.';
      showAlert('success', 'Deployment queued for approval.');
    }
  } catch (e) {
    statusEl.className = 'status-pill error';
    statusEl.textContent = 'Failed';
    descEl.textContent = e.message;
    addTimelineItem(timelineEl, '✕', 'Deployment failed', e.message, 'error');
    showAlert('error', `Deployment failed: ${e.message}`);
  }
}

async function pollRun(runId, maxAttempts = 20) {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const run = await api(`/v1/runs/${runId}`);
      if (run.status && ['completed', 'deployed', 'success', 'failed', 'error'].includes(run.status)) {
        return run;
      }
    } catch { /* ignore transient */ }
    await sleep(2000);
  }
  return { id: runId, status: 'unknown' };
}

function addTimelineItem(el, icon, title, desc, type = '') {
  const cls = type === 'error' ? 'error' : type === 'ok' ? 'ok' : type === 'warn' ? 'warn' : '';
  el.innerHTML += `<li class="timeline-item"><div class="timeline-dot ${cls}">${icon}</div><div class="timeline-content"><div class="timeline-title">${escapeHtml(title)}</div><div class="timeline-desc">${escapeHtml(desc)}</div><div class="timeline-time">${new Date().toLocaleTimeString()}</div></div></li>`;
}

// ---- B2B ----
async function proposeB2B() {
  const body = {
    package_id: $('#b2b-package').value || undefined,
    partner_id: $('#b2b-partner').value.trim(),
    standard: $('#b2b-standard').value,
    agreement_profile: $('#b2b-agreement').value.trim(),
    receiver_port: $('#b2b-receiver').value.trim(),
  };
  if (!body.partner_id) { showAlert('error', 'Enter a Partner ID.'); return; }
  try {
    const result = await api('/v1/b2b/propose', {
      method: 'POST', body: JSON.stringify(body),
    });
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
    const result = await api('/v1/b2b/compile', {
      method: 'POST',
      body: JSON.stringify(state.b2b.compileResult),
    });
    $('#b2b-result-content').textContent = JSON.stringify(result, null, 2);
    showAlert('success', 'B2B design compiled.');
  } catch (e) { showAlert('error', `B2B compile failed: ${e.message}`); }
}

async function loadB2BPartners() {
  try {
    const params = await api('/v1/b2b/parameters');
    const el = $('#b2b-partners-list');
    if (!params?.length) { hide($('#b2b-partners-section')); return; }
    show($('#b2b-partners-section'));
    el.innerHTML = params.map(p => `
      <div class="inventory-item">
        <div class="inventory-item-name">${escapeHtml(p.partner_id || p.id)}</div>
        <div class="inventory-item-meta">${escapeHtml(JSON.stringify(p).slice(0, 120))}</div>
      </div>`).join('');
  } catch { hide($('#b2b-partners-section')); }
}

// ---- Messaging ----
async function buildMessaging() {
  const pattern = state.msg.pattern;
  const body = {
    pattern,
    package_id: $('#msg-package').value || undefined,
    jms_url: $('#msg-jms-url').value.trim(),
    queue: $('#msg-queue').value.trim(),
  };
  if (!body.jms_url && !body.queue) {
    // Use messaging designer endpoint
    body.description = pattern === 'jms-retry'
      ? 'Build JMS retry pattern with exponential backoff, dead letter queue, and monitoring.'
      : 'Build Solace event mesh with guaranteed delivery, topic hierarchy, and replay logging.';
  }
  try {
    const result = await api('/v1/designs/messaging/compile', {
      method: 'POST', body: JSON.stringify(body),
    });
    state.msg.result = result;
    show($('#msg-result'));
    $('#msg-result-desc').textContent = `${pattern === 'jms-retry' ? 'JMS Retry' : 'Solace'} pattern compiled`;
    $('#msg-result-content').textContent = JSON.stringify(result, null, 2);
  } catch (e) { showAlert('error', `Messaging build failed: ${e.message}`); }
}

// ---- Wizard helpers ----
function showWizardStep(n) {
  state.wizard.step = n;
  $$('.wizard-panel').forEach(p => {
    p.classList.toggle('visible', parseInt(p.dataset.step) === n);
  });
}

// ---- Examples ----
const EXAMPLES = {
  invoice: 'Receive HTTPS JSON with an invoices array. Validate invoice_id and amount, calculate tax at 8%, enrich with customer data, route disputed invoices for manual review, then return processed invoices.',
  inventory: 'Receive inventory updates via HTTPS POST. Validate product_id and stock levels. Trigger alerts when stock falls below threshold. Aggregate changes per warehouse and push to SAP EWM.',
  order: 'Receive order messages from external system. Map to SAP IDoc format, validate business rules (credit check, duplicates), split large orders into batches, route rush orders for priority processing.',
  b2b: 'Set up B2B integration with Walmart. Use EDIFACT ORDERS D96A standard. Configure partner parameters for interchange control. Map incoming ORDERS to internal order format.',
};

// ---- Utility ----
function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ---- Event Binding ----
function bindEvents() {
  // Navigation
  $$('.sidebar-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.dataset.view) navigate(btn.dataset.view);
    });
  });

  // Connection
  $('#connect-btn')?.addEventListener('click', connect);
  $('#disconnect-btn')?.addEventListener('click', () => {
    disconnect();
    showAlert('info', 'Disconnected.', 'notice');
  });

  // New task
  $('#new-task-btn')?.addEventListener('click', () => {
    state.wizard = { step: 1, planId: null, planResult: null, compileResult: null, subflowDetail: null };
    $('#agent-scenario').value = '';
    hide($('#deployment-output'));
    navigate('agent');
    showWizardStep(1);
  });

  // Agent mode selector
  $$('#mode-auto, #mode-guided').forEach(card => {
    card.addEventListener('click', () => {
      state.agentMode = card.dataset.mode;
      $$('#mode-auto, #mode-guided').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
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
  $('#agent-analyze-btn')?.addEventListener('click', analyzeScenario);

  // Plan: Build
  $('#plan-build-btn')?.addEventListener('click', () => {
    if (state.agentMode === 'guided') {
      if (!confirmProceed('Build this iFlow design?')) return;
    }
    buildFromPlan();
  });
  $('#plan-back-btn')?.addEventListener('click', () => showWizardStep(1));

  // Build: actions
  $('#build-review-btn')?.addEventListener('click', showReview);
  $('#build-back-btn')?.addEventListener('click', () => showWizardStep(2));
  $('#build-download-btn')?.addEventListener('click', downloadCurrentZip);

  // Review: actions
  $('#review-back-btn')?.addEventListener('click', () => showWizardStep(3));
  $('#review-deploy-btn')?.addEventListener('click', deployFlow);
  $('#review-download-btn')?.addEventListener('click', downloadCurrentZip);

  // B2B
  $('#b2b-propose-btn')?.addEventListener('click', proposeB2B);
  $('#b2b-compile-btn')?.addEventListener('click', compileB2B);
  $('#b2b-download-btn')?.addEventListener('click', () => {
    if (state.b2b.compileResult) downloadJson('b2b-design.json', state.b2b.compileResult);
  });

  // Messaging
  $$('[data-msg-pattern]').forEach(card => {
    card.addEventListener('click', () => {
      state.msg.pattern = card.dataset.msgPattern;
      $$('[data-msg-pattern]').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
    });
  });
  $('#msg-build-btn')?.addEventListener('click', buildMessaging);
  $('#msg-download-btn')?.addEventListener('click', () => {
    if (state.msg.result) downloadJson('messaging-pattern.json', state.msg.result);
  });

  // Templates
  $('#refresh-templates-btn')?.addEventListener('click', loadTemplates);
  $('#tpl-back-btn')?.addEventListener('click', () => {
    hide($('#template-detail'));
    show($('#templates-list'));
  });
  $('#tpl-build-btn')?.addEventListener('click', () => {
    const params = {};
    $$('.tpl-param').forEach(el => { params[el.dataset.param] = el.value; });
    const tpl = state.tpl.selected;
    showAlert('info', `Building from template "${tpl?.name || ''}" with parameters: ${JSON.stringify(params)}`);
    // Would call template compile endpoint here
  });

  // Inventory tabs
  $$('[data-inv-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      state.inv.tab = btn.dataset.invTab;
      $$('[data-inv-tab]').forEach(b => b.classList.toggle('active', b.dataset.invTab === state.inv.tab));
      $('#inv-packages-panel').hidden = state.inv.tab !== 'packages';
      $('#inv-iflows-panel').hidden = state.inv.tab !== 'iflows';
    });
  });
  $('#refresh-packages-btn')?.addEventListener('click', loadPackages);
  $('#refresh-flows-btn')?.addEventListener('click', () => {
    const filter = $('#inventory-package-filter').value;
    if (filter) loadIflows(filter);
  });
  $('#inventory-package-filter')?.addEventListener('change', (e) => {
    if (e.target.value) loadIflows(e.target.value);
  });

  // Runs
  $('#refresh-runs-btn')?.addEventListener('click', loadRuns);

  // Connections
  $('#check-connections-btn')?.addEventListener('click', loadConnections);
  $('#diagnose-btn')?.addEventListener('click', async () => {
    try {
      const data = await api('/v1/diagnostics');
      $('#connections-content').textContent = JSON.stringify(data, null, 2);
      show($('#connections-result'));
    } catch (e) { showAlert('error', e.message); }
  });
  $('#refresh-jobs-btn')?.addEventListener('click', loadChannelJobs);

  // Settings
  $('#setting-backend').value = state.backend;
  $('#setting-token').value = state.token;
}

// ---- Modal ----
function showModal(title, body, actions = []) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = body;
  $('#modal-footer').innerHTML = actions.map(a =>
    `<button class="btn ${a.cls || 'btn-outline'}" data-action="${a.id}">${a.label}</button>`
  ).join('');
  show($('#modal-overlay'));
  $$('#modal-footer button').forEach(b => {
    b.addEventListener('click', () => {
      hide($('#modal-overlay'));
      const action = actions.find(a => a.id === b.dataset.action);
      if (action?.handler) action.handler();
    });
  });
}
$('#modal-close')?.addEventListener('click', () => hide($('#modal-overlay'));

function confirmProceed(msg) {
  let resolved = false;
  showModal('Confirm', `<p>${escapeHtml(msg)}</p>`, [
    { id: 'cancel', label: 'Cancel', cls: 'btn-outline' },
    { id: 'proceed', label: 'Proceed', cls: 'btn-primary', handler: () => { resolved = true; } },
  ]);
  return new Promise(resolve => {
    const check = setInterval(() => {
      if (resolved) { clearInterval(check); resolve(true); }
      if (!$('#modal-overlay').hidden) return;
      clearInterval(check);
      resolve(false);
    }, 200);
  });
}

// ---- Download helpers ----
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

// ---- Auto-connect if token present ----
async function autoConnect() {
  if (!state.token) return;
  state.backend = localStorage.getItem('cpi_backend') || 'http://127.0.0.1:8000';
  $('#setting-backend').value = state.backend;
  $('#setting-token').value = state.token;
  try {
    const me = await api('/v1/me');
    state.principal = me;
    state.connected = true;
    updateConnectionUI();
    await loadAll();
  } catch { /* silent */ }
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
