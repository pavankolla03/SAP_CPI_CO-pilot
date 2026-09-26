import { showDiagram, setPane } from './studio.js';
const $ = (id) => document.getElementById(id);
const storage = globalThis.chrome?.storage?.session;
let base = location.protocol.startsWith('http') ? location.origin : 'http://127.0.0.1:8000';
let generatedDesign = null, solutionPlan = null;
let token = '', me = null, current = null, busy = false;
let packageCache = [], selectedPackage = '', activeTab = 'agent';
const json = (x) => JSON.stringify(x, null, 2);
const labels = {discover:'Workspace discovered',plan:'Plan prepared',approve:'Approval recorded',execute:'Tool executed',observe:'Deployment observed',validate:'Result validated',test:'Smoke test evaluated',fix:'Remediation reviewed',redeploy:'Redeployment requested',verify:'Verification complete',audit:'Audit recorded',requested:'Run requested',error:'Needs attention'};
function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
async function api(path, body) {
  const response = await fetch(base + path, {method: body === undefined ? 'GET' : 'POST', headers: {'Authorization': `Bearer ${token}`, 'Content-Type':'application/json'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : json(data.detail));
  return data;
}
async function attempt(fn) {
  if (busy) return;
  busy = true; notice();
  document.querySelectorAll('#package-create-button,#plan-button,#approve,#reject,#resume,#connect,#draft-ai,#design-propose,#design-compile,#design-use,#messaging-build,#description-build,#solution-build').forEach(b => b.disabled = true);
  try { await fn(); } catch (error) { notice(error.message); if ($('design-explanation').textContent.startsWith('Generating')) $('design-explanation').textContent='Generation stopped. '+error.message; }
  finally { busy = false; document.querySelectorAll('#package-create-button,#plan-button,#approve,#reject,#resume,#connect,#draft-ai,#design-propose,#design-compile,#design-use,#messaging-build,#description-build,#solution-build').forEach(b => b.disabled = false); $('solution-build').disabled = !solutionPlan?.buildable; }
}
function tab(name) {
  activeTab = name;
  for (const button of document.querySelectorAll('[data-tab]')) { button.classList.toggle('selected', button.dataset.tab === name); button.setAttribute('aria-selected', String(button.dataset.tab === name)); }
  for (const value of ['package-create','agent','advanced','inventory','history','capabilities']) $(`tab-${value}`).hidden = value !== name;
  $('run').hidden = !current || !['agent','package-create','advanced'].includes(name);
  placeRun();
  if(name==='agent'&&current&&!generatedDesign)setPane('review');
  $('empty-state').hidden = true;
}
function placeRun() {
  if(activeTab==='agent')$('studio-review').append($('run'));
  else $('empty-state').before($('run'));
}
function destination() {
  selectedPackage = $('design-package').value;
  const p = packageCache.find(p => p.Id === selectedPackage);
  $('iflow-destination').textContent = p ? `Destination: ${p.Name || p.Id} · ${p.Id}` : 'Select a package. Create a new one from the left navigation if needed.';
}
async function loadDesignPackages(preferred) {
  if (!me) return;
  const wanted = preferred || $('design-package').value || selectedPackage;
  packageCache = await api('/v1/packages');
  $('design-package').replaceChildren(new Option('Choose a package…', ''), ...packageCache.map(p => new Option(`${p.Name || p.Id} (${p.Id})`, p.Id)));
  $('design-package').value = packageCache.some(p => p.Id === wanted) ? wanted : '';
  destination();
}
$('refresh-design-packages').onclick = () => attempt(loadDesignPackages);
$('design-package').addEventListener('change', () => { resetRun(); destination(); });
$('package-create-form').onsubmit = event => {
  event.preventDefault();
  attempt(async () => {
    if (!me) throw Error('Connect your workspace first.');
    render(await api('/v1/runs', {action:'create_package',package_id:$('new-package-id').value.trim(),name:$('new-package-name').value.trim(),goal:'Create a DEV integration package'}));
    $('run').scrollIntoView({behavior:'smooth',block:'start'});
  });
};
function resetRun() { solutionPlan=null; $('solution-content').hidden=true; $('solution-title').textContent='Your integration plan'; $('solution-summary').textContent='Describe a scenario to see the requirements, proposed flows and questions here.'; $('solution-status').textContent='Waiting for your idea'; $('solution-build').disabled=true; generatedDesign = null; $('design-preview').hidden = true; current = null; $('run').hidden = true; $('empty-state').hidden = true; setPane('describe'); }
async function connect() {
  const candidate = new URL($('backend').value);
  if (!(['http:', 'https:'].includes(candidate.protocol)) || candidate.username || candidate.password || candidate.search || candidate.hash) throw Error('Enter an HTTP(S) backend origin.');
  if (candidate.protocol !== 'https:' && !['localhost','127.0.0.1'].includes(candidate.hostname)) throw Error('Remote backends require HTTPS.');
  base = candidate.origin;
  token = $('token').value.trim();
  me = null; resetRun();
  me = await api('/v1/me');
  $('workspace-name').textContent = me.tenant_name;
  $('mode').textContent = `${me.mode.toUpperCase()} · DEV`;
  $('connection-dot').classList.add('connected');
  $('settings').hidden = true;
  if (storage) await storage.set({base, token});
  else sessionStorage.setItem('relay-connection', json({base, token}));
  await history();
  await loadDesignPackages();
}
$('settings-toggle').onclick = () => $('settings').hidden = !$('settings').hidden;
$('connect').onclick = () => attempt(connect);
$('disconnect').onclick = async () => {
  token = ''; me = null; resetRun(); $('token').value = '';
  if (storage) await storage.remove(['base','token']); else sessionStorage.removeItem('relay-connection');
  $('workspace-name').textContent = 'No workspace connected'; $('mode').textContent = 'OFFLINE';
  $('connection-dot').classList.remove('connected'); $('packages').replaceChildren(); $('flows').replaceChildren(); $('history').replaceChildren();
};
for (const button of document.querySelectorAll('[data-tab]')) button.onclick = () => {
  tab(button.dataset.tab);
  if (button.dataset.tab === 'inventory') attempt(inventory);
  if (button.dataset.tab === 'history') attempt(history);
  if (button.dataset.tab === 'capabilities') attempt(checkServices);
  if (button.dataset.tab === 'agent') attempt(loadDesignPackages);
};
$('action').onchange = () => {
  const action = $('action').value;
  $('package-field').hidden = action === 'create_partner_parameter';
  $('package').required = action !== 'create_partner_parameter';
  $('artifact').required = ['deploy','upload','upload_deploy'].includes(action);
  $('partner-fields').hidden = action !== 'create_partner_parameter';
  $('upload-field').hidden = !['upload','upload_deploy'].includes(action);
  $('name-field').hidden = action !== 'create_package';
  $('artifact-field').hidden = $('version-field').hidden = ['create_package','create_partner_parameter'].includes(action);
};
$('run-form').onsubmit = (event) => {
  event.preventDefault();
  attempt(async () => {
    if (!me) throw Error('Connect your workspace first.');
    let artifact_content = null;
    if (['upload','upload_deploy'].includes($('action').value)) {
      const file = $('bundle').files[0];
      if (!file && generatedDesign && generatedDesign.design.package_id === $('package').value && generatedDesign.design.artifact_id === $('artifact').value) { artifact_content = generatedDesign.artifact_content; }
      else {
      if (!file || file.size > 4000000) throw Error('Choose an iFlow ZIP under 4 MB, or build a design with matching IDs.');
      artifact_content = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.onerror = reject; reader.readAsDataURL(file); });
      }
    }
    const result = await api('/v1/runs', {goal:$('goal').value, action:$('action').value, package_id:$('package').value, artifact_id:$('artifact').value, name:$('package-name').value, version:$('version').value, partner_id:$('partner-id').value, parameter_id:$('parameter-id').value, parameter_value:$('parameter-value').value, artifact_content});
    render(result);
    $('run').scrollIntoView({behavior:'smooth',block:'start'});
  });
};
function render(run) {
  if (current && JSON.stringify(current) === JSON.stringify(run)) return;
  if(generatedDesign?.run && generatedDesign.run.id!==run.id){generatedDesign=null;$('design-preview').hidden=true;}
  const newlySucceeded = run.status === 'succeeded' && (current?.id !== run.id || current?.status !== 'succeeded');
  current = run; $('run').hidden = !['agent','package-create','advanced'].includes(activeTab); $('empty-state').hidden = true;
  placeRun();
  if(activeTab==='agent'&&!generatedDesign)setPane('review');
  const target = run.plan?.after || {};
  $('creation-status').textContent = run.status === 'succeeded' ? `${target.action === 'create_package' ? 'Package created' : 'iFlow ready'}: ${target.artifact_id && target.action !== 'create_package' ? target.artifact_id + ' in ' : ''}${target.package_id || ''}` : run.pending?.length ? `Ready to review. Nothing has been created yet. Destination package: ${target.package_id || '—'}` : `${run.status || 'Working'} · ${target.package_id || ''}`;
  $('view-created').hidden = run.status !== 'succeeded';
  if (newlySucceeded) loadDesignPackages(target.package_id).catch(error => notice('Created successfully, but package refresh failed: '+error.message));
  $('run-title').textContent = run.plan?.after?.action === 'create_package' ? 'Package creation' : run.plan?.after?.action === 'create_partner_parameter' ? 'Partner configuration' : run.plan?.after?.action === 'upload' ? 'iFlow design upload' : 'iFlow deployment';
  $('run-short').textContent = run.id?.slice(0,8) || '';
  $('run-status').textContent = (run.status || 'running').replaceAll('_',' ').toUpperCase();
  $('plan-goal').textContent = run.plan?.goal || run.error || 'Discovering workspace…';
  $('operations').replaceChildren(...(run.plan?.operations || []).map(op => { const li = document.createElement('li'); li.textContent = op.replaceAll('_',' '); return li; }));
  $('risk').textContent = run.plan?.risk || '';
  $('before').textContent = json(run.plan?.before || {});
  $('after').textContent = json(run.plan?.after || {});
  $('bundle-details').hidden = !run.plan?.bundle;
  $('bundle-info').textContent = json(run.plan?.bundle || {});
  const pending = run.pending?.[0];
  $('approval-message').textContent = pending?.message || (pending ? 'Review the change and its scope before approving.' : run.error || run.plan?.test_scope || '');
  $('approval-actions').hidden = !pending || me?.role !== 'approver';
  $('approve').textContent = pending?.kind === 'repair_approval' ? 'Approve one retry →' : target.action === 'create_package' ? 'Create package →' : target.action === 'upload_deploy' ? 'Create iFlow & deploy →' : target.action === 'upload' ? 'Create iFlow →' : 'Approve & execute →';
  $('resume').hidden = !!pending || !['running', 'needs_attention'].includes(run.status) || me?.role !== 'approver';
  $('timeline').replaceChildren(...(run.events || []).map(event => {
    const li = document.createElement('li'); li.className = event.phase;
    const title = document.createElement('div'); title.className = 'event-title'; title.textContent = labels[event.phase] || event.phase;
    const time = document.createElement('time'); time.textContent = new Date(event.at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}); title.append(time);
    const detail = document.createElement('div'); detail.className = 'event-detail';
    detail.textContent = event.data.message || event.data.tool || event.data.status || (event.data.passed === false ? 'Check failed' : event.data.passed === true ? 'Check passed' : event.data.actor || '');
    const disclosure = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'Evidence';
    const evidence = document.createElement('pre'); evidence.textContent = json(event.data); disclosure.append(summary,evidence); li.append(title,detail,disclosure); return li;
  }));
  $('test-card').hidden = !run.test;
  $('test-code').textContent = run.test?.code || '';
  $('test-scope').textContent = run.test ? `${run.test.passed ? 'Passed' : 'Failed'} · ${run.test.scope}` : '';
}
for (const approve of [true,false]) $(approve ? 'approve' : 'reject').onclick = () => attempt(async () => {
  if ($('background-mode').checked) {
    const result = await api('/v1/channel-jobs/decision', {run_id:current.id, approve, plan_hash:current.plan_hash});
    $('approval-actions').hidden=true; notice(`Background job ${result.job_id} queued. Follow Activity; keep the backend running.`);
  } else render(await api(`/v1/runs/${current.id}/decision`, {approve, plan_hash:current.plan_hash}));
});
$('resume').onclick = () => attempt(async () => render(await api(`/v1/runs/${current.id}/resume`, {})));
function item(title, description, action) { const b = document.createElement('button'); b.className = 'item'; b.textContent = title; const s = document.createElement('span'); s.textContent = description; b.append(s); b.onclick = () => attempt(action); return b; }
async function inventory() {
  const packages = await api('/v1/packages'); $('flows').replaceChildren(); $('selected-package-title').hidden=true; $('artifact-detail').hidden = true;
  $('packages').replaceChildren(...packages.map(p => item(p.Name || p.Id, p.Id + ' →', async () => {
    $('package').value = p.Id; $('design-package').value = p.Id; destination();
    $('selected-package-title').hidden=false;$('selected-package-title').textContent=`iFlows in ${p.Name || p.Id}`;
    const flows = await api(`/v1/packages/${encodeURIComponent(p.Id)}/iflows`);
    $('flows').replaceChildren(...flows.map(f => item(f.Name || f.Id, `${f.Id} · ${f.Version}`, async () => {
      $('artifact').value = f.Id;
      const id = encodeURIComponent(f.Id);
      const results = await Promise.allSettled([api(`/v1/iflows/${id}`), api(`/v1/iflows/${id}/runtime`), api(`/v1/iflows/${id}/mpl`)]);
      const detail = Object.fromEntries(['design','runtime','message_logs'].map((name,index) => [name,results[index].status === 'fulfilled' ? results[index].value : {unavailable:results[index].reason.message}]));
      $('artifact-detail').hidden = false; $('artifact-detail').textContent = json(detail);
      $('goal').value = `Deploy ${f.Id} and verify it is running.`;
      notice(`${f.Id} selected in ${p.Id}. Use Advanced tools to deploy an existing iFlow.`);
    })));
    if (!flows.length) $('flows').textContent = 'This package has no iFlows.';
  })));
  if (!packages.length) $('packages').textContent = 'No packages yet. Create one from the Agent tab.';
}
$('view-created').onclick = () => attempt(async () => {
  const packageId = current.plan.after.package_id;
  await loadDesignPackages(packageId);
  tab('inventory'); await inventory();
  const flows = await api(`/v1/packages/${encodeURIComponent(packageId)}/iflows`);
  $('selected-package-title').hidden=false;$('selected-package-title').textContent=`iFlows in ${packageId}`;
  $('flows').replaceChildren(...flows.map(f => item(f.Name || f.Id, `${packageId} · ${f.Id}`, async () => {
    $('artifact-detail').hidden=false; $('artifact-detail').textContent=json(await api(`/v1/iflows/${encodeURIComponent(f.Id)}`));
  })));
  notice(`${packageId}: ${flows.length} iFlow(s). To add another, choose Create iFlow on the left.`);
});
async function history() {
  const runs = await api('/v1/runs');
  $('history').replaceChildren(...runs.map(r => item(r.id.slice(0,8), new Date(r.created).toLocaleString(), async () => { render(await api(`/v1/runs/${r.id}`)); tab('agent'); $('run').scrollIntoView({behavior:'smooth',block:'start'}); })));
  if (!runs.length) $('history').textContent = 'Your approved and proposed runs will appear here.';
}
$('refresh-artifacts').onclick = () => attempt(inventory);
$('refresh-history').onclick = () => attempt(history);
$('download-test').onclick = () => { const url = URL.createObjectURL(new Blob([current.test.code], {type:'text/x-python'})); const a = document.createElement('a'); a.href = url; a.download = 'test_dev_smoke.py'; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000); };
setInterval(async () => {
  if (!current || !token) return;
  const id = current.id;
  try { const value = await api(`/v1/runs/${id}`); if (current?.id === id) render(value); } catch { /* Explicit actions surface connection failures. */ }
}, 2000);
const saved = storage ? await storage.get(['base','token']) : JSON.parse(sessionStorage.getItem('relay-connection') || '{}');
$('backend').value = saved.base || base; $('token').value = saved.token || '';
if (saved.token) attempt(connect);

$('draft-ai').onclick = () => attempt(async () => {
  if (!me) throw Error('Connect your workspace first.');
  $('ai-result').textContent = 'Drafting with a verified free model…';
  try {
    const result = await api('/v1/proposals', {goal:$('goal').value});
    $('ai-result').textContent = `${result.model || 'Free model'} · ${result.explanation}`;
    if (!result.supported) return;
    $('action').value = result.request.action; $('package').value = result.request.package_id;
    $('artifact').value = result.request.artifact_id; $('package-name').value = result.request.name;
    $('version').value = result.request.version; $('action').onchange();
    notice('Draft ready. Review the target IDs, then create a plan. Nothing has executed.');
  } catch (error) { $('ai-result').textContent = 'Draft unavailable. You can still use the workflow form.'; throw error; }
});
async function checkServices() {
  $('capabilities').textContent = 'Checking configured services…';
  $('service-inventory').hidden = true;
  const data = await api('/v1/capabilities');
  $('capabilities').replaceChildren(...data.results.map(result => item(
    `${result.capability.replaceAll('_',' ')} · ${result.status.replaceAll('_',' ')}`,
    result.detail + (data.mode === 'demo' ? ' (Demo adapter)' : ''), async () => {
      const path = {apim:'/v1/apim/proxies', aem:'/v1/aem/services', b2b_partner_directory:'/v1/b2b/parameters'}[result.capability];
      if (result.status !== 'accessible' || !path) return;
      $('service-inventory').textContent = json(await api(path)); $('service-inventory').hidden = false;
    }
  )));
}
$('check-services').onclick = () => attempt(checkServices);

$('new-task').onclick = () => {
  if (busy) return;
  resetRun(); $('run-form').reset(); $('action').onchange(); tab('agent');
  document.querySelector('.target-settings').open = false;
  $('ai-result').textContent = 'Only your goal is sent to the AI. Every change is yours to approve.';
  notice('New task ready. Previous runs remain in Activity.');
  document.querySelector('.scroll-area').scrollTo({top:0,behavior:'smooth'});
  $('design-scenario').focus();
};
for (const button of document.querySelectorAll('[data-preset]')) button.onclick = () => {
  if (busy) return;
  $('action').value = button.dataset.preset;
  if (button.dataset.preset === 'create_package') {
    $('package').value = 'RelayPackage'; $('package-name').value = 'Relay Package';
    $('goal').value = 'Create a DEV package with package_id RelayPackage and name Relay Package.';
  } else {
    $('goal').value = `Deploy artifact_id ${$('artifact').value} in package_id ${$('package').value}, version ${$('version').value}.`;
  }
  $('action').onchange(); $('goal').focus();
};
for (const button of document.querySelectorAll('[role="tab"]')) button.addEventListener('keydown', event => {
  const keys = ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'];
  if (!keys.includes(event.key)) return;
  event.preventDefault();
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  let index = tabs.indexOf(button);
  if (event.key === 'Home') index = 0;
  else if (event.key === 'End') index = tabs.length - 1;
  else index = (index + (['ArrowRight','ArrowDown'].includes(event.key) ? 1 : -1) + tabs.length) % tabs.length;
  tabs[index].focus(); tabs[index].click();
});

$('diagnose-sap').onclick = () => attempt(async () => {
  const report = await api('/v1/diagnostics');
  $('service-inventory').textContent = json(report);
  $('service-inventory').hidden = false;
});

function orderTarget() { return {package_id:$('design-package').value.trim(),artifact_id:$('design-artifact').value.trim(),endpoint_path:$('design-endpoint').value.trim()}; }
function orderSpec() { return {...orderTarget(),pattern:'batch_orders',title:'Process orders by ID',review_threshold:Number($('design-threshold').value),max_orders:Number($('design-limit').value)}; }
for (const id of ['design-scenario','design-package','design-artifact','design-endpoint','design-threshold','design-limit','scenario-pattern','acceptance-input','acceptance-output','scenario-answers']) $(id).addEventListener('input', resetRun);
const scenarioExamples={
  invoice:{pattern:'auto',text:'Receive HTTPS JSON with an invoices array. Require id, quantity and unitPrice for each invoice. Remove duplicate invoices by id, calculate total as quantity multiplied by unitPrice, route totals greater than 5000 to MANUAL_REVIEW and the rest to APPROVED, and return results in an invoices array.'},
  inventory:{pattern:'auto',text:'Receive HTTPS JSON with an items array. Require sku, available and reorderLevel. Keep only items where available is less than reorderLevel, map sku to productCode in uppercase, calculate shortage as reorderLevel minus available, sort by shortage descending, and return the results in an alerts array.'},
  employee:{pattern:'auto',text:'Receive one HTTPS JSON employee object. Require employee.id, employee.name and employee.email. Map employee.id to employeeId, employee.name to displayName in uppercase, employee.email to email in lowercase, and return the normalized JSON object.'}
};
for(const button of document.querySelectorAll('[data-example]')) button.onclick=()=>{
  const example=scenarioExamples[button.dataset.example];$('scenario-pattern').value=example.pattern;$('design-scenario').value=example.text;
  $('design-scenario').dispatchEvent(new Event('input',{bubbles:true}));$('design-explanation').textContent='Example loaded. Edit it if needed, then generate a review.';
};
$('design-propose').onclick = () => attempt(async () => {
  if (!me) throw Error('Connect your workspace first.');
  generatedDesign = null; $('design-preview').hidden = true;
  const result = await api('/v1/designs/orders/propose', {...orderTarget(),scenario:$('design-scenario').value});
  const draft = result.draft;
  $('design-explanation').textContent = `${draft.explanation} ${draft.questions.join(' ')} (${result.model || 'Free AI'})`;
  if (draft.supported && draft.design) { $('design-threshold').value = draft.design.review_threshold; $('design-limit').value = draft.design.max_orders; }
});
$('design-compile').onclick = () => attempt(async () => {
  if (!me) throw Error('Connect your workspace first.');
  generatedDesign = null; $('design-preview').hidden = true;
  const result = await api('/v1/designs/orders/compile', orderSpec());
  generatedDesign = result;
  $('design-use').hidden=false;$('design-download').hidden=false;
  $('design-preview').hidden = false;
  $('design-steps').replaceChildren(...result.steps.map(text => {const li=document.createElement('li');li.textContent=text;return li;}));
  $('design-evidence').textContent=json({design:result.design,bundle:result.bundle,scripts:result.scripts,test_cases:result.test_cases});
  $('design-sample').textContent=json(result.sample_input);
  notice('Native iFlow design built. Inspect the steps and scripts before approving deployment.');
});
$('design-download').onclick = () => {
  if (!generatedDesign) return;
  const bytes=Uint8Array.from(atob(generatedDesign.artifact_content),c=>c.charCodeAt(0));
  const url=URL.createObjectURL(new Blob([bytes],{type:'application/zip'}));
  const a=document.createElement('a');a.href=url;a.download=generatedDesign.design.artifact_id+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
$('design-use').onclick = () => {
  if (!generatedDesign || busy) return;
  const spec=generatedDesign.design;
  $('action').value='upload_deploy';$('package').value=spec.package_id;$('artifact').value=spec.artifact_id;$('version').value='active';$('bundle').value='';
  $('goal').value=`Create ${spec.artifact_id}: HTTPS batch orders, General Splitter, Router, Gather and Exception Subprocesses. Review threshold ${spec.review_threshold}, maximum ${spec.max_orders} orders. No external receiver.`;
  $('action').onchange();$('run-form').requestSubmit();
};

$('messaging-build').onclick = () => attempt(async () => {
  if (!me) throw Error('Connect your workspace first.');
  const result = await api('/v1/designs/messaging/compile', {retry_limit:3,retry_interval_minutes:1});
  $('messaging-designs').replaceChildren(...result.flows.map(flow => item(flow.artifact_id, `${flow.package_id} · ${flow.configuration_required ? 'Upload only; configure Solace first' : 'JMS broker required'}`, async () => {
    $('design-preview').hidden=true;
    generatedDesign={...flow, design:{package_id:flow.package_id,artifact_id:flow.artifact_id}};
    $('action').value=flow.configuration_required ? 'upload' : 'upload_deploy';
    $('package').value=flow.package_id;$('artifact').value=flow.artifact_id;$('version').value='active';$('bundle').value='';
    $('goal').value=`${flow.configuration_required ? 'Upload undeployed design' : 'Upload and deploy DEV test flow'} ${flow.artifact_id}. Existing IDs cannot be overwritten.`;
    $('action').onchange();notice('Design selected. Use Review my plan to inspect its fingerprint and approve. Existing IDs require choosing a new scenario version.');
    $('run-form').scrollIntoView({behavior:'smooth',block:'start'});
  })));
});

let recorder = null, recordingStream = null, recordingTimer = null, recordingCancelled = false;
async function transcribeAudio(blob) {
  if (!me) throw Error('Connect your workspace first.');
  if (!blob.size || blob.size > 5000000) throw Error('Choose audio under 5 MB.');
  $('voice-state').textContent='Transcribing locally…';
  const response = await fetch(base + '/v1/voice/transcribe', {method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':blob.type || 'audio/wav'},body:blob});
  const result=await response.json();
  if (!response.ok) throw Error(typeof result.detail==='string' ? result.detail : 'Transcription failed.');
  $('voice-transcript').value=result.text;
  $('voice-state').textContent=`${result.seconds}s · ${result.language} · Review the transcript before continuing.`;
}
function stopRecording() {
  clearTimeout(recordingTimer);
  if (recorder?.state === 'recording') recorder.stop();
  recordingStream?.getTracks().forEach(track=>track.stop());
  $('voice-stop').disabled=true; $('voice-record').disabled=false;
}
$('voice-record').onclick = async () => {
  if (busy || $('voice-record').disabled || recorder?.state==='recording') return;
  $('voice-record').disabled=true;
  try {
    if (!me) throw Error('Connect your workspace first.');
    const status=await api('/v1/channels');
    if (!status.voice.enabled || !status.voice.model_ready) throw Error('Local voice model is not ready. See the voice setup guide.');
    if (!navigator.mediaDevices?.getUserMedia || !globalThis.MediaRecorder) throw Error('Microphone recording is unavailable here. Upload a recording instead.');
    recordingStream=await navigator.mediaDevices.getUserMedia({audio:true});
    const mime=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
    recorder=new MediaRecorder(recordingStream,mime ? {mimeType:mime} : undefined);
    const chunks=[];let size=0;recordingCancelled=false;
    recorder.ondataavailable=event=>{ chunks.push(event.data);size+=event.data.size;if(size>5000000)stopRecording(); };
    recorder.onerror=()=>{recordingCancelled=true;stopRecording();notice('Recording failed. Try uploading an audio file.');};
    recorder.onstop=()=>{if(!recordingCancelled)attempt(async()=>{try{await transcribeAudio(new Blob(chunks,{type:recorder.mimeType}));}catch(e){$('voice-state').textContent=e.message;throw e;}});};
    recorder.start(1000);$('voice-record').disabled=true;$('voice-stop').disabled=false;
    $('voice-state').textContent='Recording… stops automatically after 60 seconds.';
    recordingTimer=setTimeout(stopRecording,59000);
  } catch(error) {stopRecording();notice(error.message);}
};
$('voice-stop').onclick=stopRecording;
$('voice-file').onchange=()=>attempt(async()=>{const file=$('voice-file').files[0];if(file)await transcribeAudio(file);});
for(const target of ['order','goal']) $('voice-'+target).onclick=()=>{
  const text=$('voice-transcript').value.trim();if(!text)return notice('Record or enter a scenario first.');
  tab(target==='order'?'agent':'advanced');
  const field=$(target==='order'?'design-scenario':'goal');field.value=text;field.dispatchEvent(new Event('input',{bubbles:true}));field.focus();field.scrollIntoView({behavior:'smooth',block:'center'});
  notice('Transcript copied. Check target IDs, then interpret/build or review your plan.');
};
window.addEventListener('pagehide',()=>{recordingCancelled=true;stopRecording();});
$('channel-status').onclick=()=>attempt(async()=>{$('channel-detail').hidden=false;$('channel-detail').textContent=json(await api('/v1/channels'));});
$('refresh-channel-jobs').onclick=()=>attempt(async()=>{
  const jobs=await api('/v1/channel-jobs');
  $('channel-jobs').replaceChildren(...jobs.map(job=>item(`${job.source} · ${job.state}`,job.result.message || 'Queued',async()=>{
    if(job.result.run_id){tab('agent');render(await api('/v1/runs/'+job.result.run_id));}
  })));
  if(!jobs.length)$('channel-jobs').textContent='No channel jobs yet.';
});

const scenarioSnapshot=()=>JSON.stringify(['design-scenario','design-package','acceptance-input','acceptance-output','scenario-answers'].map(id=>$(id).value));
function listText(id, rows){$(id).replaceChildren(...rows.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));}
function showSolution(plan){
  solutionPlan=plan;
  $('solution-content').hidden=false;
  $('solution-title').textContent=plan.title;
  $('solution-summary').textContent=plan.summary;
  $('solution-status').textContent={ready:'Ready to build',needs_answers:'Needs your answers',not_buildable:'Architecture only · build blocked'}[plan.status];
  $('solution-status').dataset.status=plan.status;
  listText('solution-requirements',plan.requirements.map(r=>r.description));
  $('solution-flows').replaceChildren(...plan.flows.map((flow,index)=>{
    const card=document.createElement('article');card.className='solution-flow';
    const head=document.createElement('h4');head.textContent=String(index+1).padStart(2,'0')+' / '+flow.name;
    const p=document.createElement('p');p.textContent=flow.purpose;
    const path=document.createElement('div');path.className='flow-path';path.textContent=flow.sender+' → '+flow.receiver;
    const steps=document.createElement('ol');for(const step of flow.steps){const li=document.createElement('li');li.textContent=step;steps.append(li);}
    card.append(head,p,path,steps);return card;
  }));
  listText('solution-blockers',plan.blockers);$('solution-blocker-section').hidden=!plan.blockers.length;
  listText('solution-questions',plan.questions);$('solution-question-section').hidden=!plan.questions.length;
  listText('solution-assumptions',plan.assumptions);$('solution-assumptions-section').hidden=!plan.assumptions.length;
  $('solution-test-status').textContent=plan.acceptance.status==='passed_locally'?'✓ Your expected output matches the local simulation. SAP runtime verification happens after deployment.':'Business output not verified. Add sample input and expected output for an acceptance check.';
  $('solution-sources').replaceChildren(...plan.references.map(ref=>{const li=document.createElement('li'),a=document.createElement('a');if(!ref.url?.startsWith('https://'))return li;a.href=ref.url;a.rel='noopener';a.target='_blank';a.textContent=ref.title+' · '+(ref.status||'curated');li.append(a);return li;}));
  $('solution-meta').textContent=json({fingerprint:plan.fingerprint,model:plan.model,key_slots:plan.key_slots,free_only:plan.free_only,coverage_review:plan.coverage_review});
  $('solution-build').disabled=!plan.buildable;
  setPane('plan');
}
$('solution-edit').onclick=()=>{setPane('describe');$('clarification-editor').open=true;$('scenario-answers').focus();};
$('description-build').onclick=()=>attempt(async()=>{
  if(!me)throw Error('Connect your workspace first.');
  if(!$('design-package').value)throw Error('Choose the package where this iFlow should be created.');
  const sample_input=$('acceptance-input').value.trim()?JSON.parse($('acceptance-input').value):null;
  const expected_output=$('acceptance-output').value.trim()?JSON.parse($('acceptance-output').value):null;
  resetRun();
  $('design-explanation').textContent='Generating your plan: researching SAP references, interpreting requirements and checking coverage…';
  const sourceSnapshot=scenarioSnapshot();
  const result=await api('/v1/solutions/analyze',{description:$('design-scenario').value,clarifications:$('scenario-answers').value,package_id:$('design-package').value.trim(),sample_input,expected_output});
  if(sourceSnapshot!==scenarioSnapshot())throw Error('Your requirements changed during planning. Plan again to use the updated request.');
  $('design-explanation').textContent=result.summary;
  showSolution(result);
  notice(result.buildable?'Plan ready. Review the requirements before building the diagram.':'Review the questions and blockers. No iFlow has been created.');
});
$('solution-build').onclick=()=>attempt(async()=>{
  if(!solutionPlan?.buildable)throw Error('Resolve the plan blockers first.');
  const sourceSnapshot=scenarioSnapshot();
  const result=await api('/v1/solutions/'+solutionPlan.id+'/build',{});
  if(sourceSnapshot!==scenarioSnapshot())throw Error('Requirements changed during build. Plan again before reviewing a deployment.');
  const sample_input=$('acceptance-input').value.trim()?JSON.parse($('acceptance-input').value):null;
  const expected_output=$('acceptance-output').value.trim()?JSON.parse($('acceptance-output').value):null;
  $('design-artifact').value=result.design.artifact_id;$('design-endpoint').value=result.design.endpoint_path;
  generatedDesign=result;
  $('design-preview').hidden=false;$('design-use').hidden=true;$('design-download').hidden=false;
  await showDiagram(result);
  listText('design-steps',result.steps);
  $('design-evidence').textContent=json({pattern:result.pattern,design:result.design,scripts:result.scripts,test_cases:result.test_cases,bundle:result.bundle,free_model:result.model,plan_fingerprint:result.plan_fingerprint});
  $('design-sample').textContent=sample_input===null?'No sample supplied. Business-output acceptance has not been tested for this proposal.':json({status:expected_output===null?'Simulated; no expected output supplied':'Expected output matched in local simulation',input:result.sample_input,output:result.sample_output,expected:expected_output});
  render(result.run);setPane('diagram');
  notice('Built from your reviewed plan without regenerating it. Inspect the diagram, then review deployment.');
});
