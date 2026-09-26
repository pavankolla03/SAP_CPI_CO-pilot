// Display the exact BPMN document contained in the approved SAP bundle.
let viewer, xml = '';
const $ = id => document.getElementById(id);
export function setPane(pane) {
  $('studio-workbench').dataset.pane= pane;
  for(const button of document.querySelectorAll('[data-pane]')) if(button.tagName==='BUTTON')button.setAttribute('aria-pressed',String(button.dataset.pane===pane));
  if(pane==='diagram' && viewer)requestAnimationFrame(()=>viewer.get('canvas').zoom('fit-viewport'));
}
for(const button of document.querySelectorAll('button[data-pane]'))button.onclick=()=>{setPane(button.dataset.pane);const id={describe:'studio-composer',plan:'studio-plan',diagram:'studio-canvas',review:'studio-review'}[button.dataset.pane];$(id).scrollIntoView({behavior:'smooth',block:'nearest'});};
$('review-design').onclick=()=>{setPane('review');$('studio-review').scrollIntoView({behavior:'smooth',block:'start'});};
export async function showDiagram(result) {
  setPane('diagram');
  xml = result.bpmn_xml || '';
  if (!xml) {
    $('diagram-status').textContent = 'This legacy design does not expose a BPMN preview.';
    if(viewer)viewer.clear();
    return;
  }
  if(!viewer){
    viewer = new window.BpmnJS({container:'#bpmn-canvas'});
    viewer.on('element.click',event=>{
      const id=event.element.id;
      const doc=new DOMParser().parseFromString(xml,'application/xml');
      const node=[...doc.getElementsByTagName('*')].find(n=>n.getAttribute('id')===id);
      if(!node)return;
      const props={id,name:node.getAttribute('name'),type:node.localName};
      for(const entry of [...node.getElementsByTagName('*')].filter(n=>n.localName==='property')){
        const key=entry.getElementsByTagName('key')[0]?.textContent;
        if(key)props[key]=entry.getElementsByTagName('value')[0]?.textContent;
      }
      $('step-properties').hidden=false;$('step-properties').textContent=JSON.stringify(props,null,2);
    });
  }
  try{
    $('step-properties').hidden=true;
    await viewer.importXML(xml);
    viewer.get('canvas').zoom('fit-viewport');
    $('diagram-status').textContent='Preview of the exact iFlow bundle · scroll to zoom, drag to pan, click to inspect.';
  }catch(error){$('diagram-status').textContent='Diagram preview failed: '+error.message;throw error;}
  $('research-sources').replaceChildren(...(result.references||[]).map(ref=>{
    const li=document.createElement('li');const a=document.createElement('a');
    if(!ref.url?.startsWith('https://'))return li;
    a.href=ref.url;a.target='_blank';a.rel='noopener';a.textContent=ref.title;
    const info=document.createElement('span');info.textContent=' — '+(ref.status||'curated reference');li.append(a,info);return li;
  }));
}
$('diagram-fit').onclick=()=>viewer?.get('canvas').zoom('fit-viewport');
$('diagram-plus').onclick=()=>{if(viewer){const c=viewer.get('canvas');c.zoom(c.zoom()*1.25);}};
$('diagram-minus').onclick=()=>{if(viewer){const c=viewer.get('canvas');c.zoom(c.zoom()/1.25);}};
$('diagram-export').onclick=()=>{
  if(!xml)return;
  const url=URL.createObjectURL(new Blob([xml],{type:'application/xml'}));
  const a=document.createElement('a');a.href=url;a.download='relay-proposed-iflow.bpmn';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
