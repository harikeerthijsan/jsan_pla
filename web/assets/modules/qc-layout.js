// QC four-view layout: maximize, minimize, focus workspace and resize.
import { $, state, toast } from "./core.js?v=20261009-directory-422";
import { renderAnalysisViews } from "./qc-analysis.js?v=20261009-directory-422";

export function refreshViewLayout(){
  const grid=document.querySelector('.quad-grid');
  if(!grid)return;
  const cards=[...grid.querySelectorAll('.view-card')];
  grid.classList.toggle('has-maximized',!!state.layout.maximized);
  for(const card of cards){
    const key=card.dataset.view;
    card.classList.toggle('minimized',state.layout.minimized.has(key));
    card.classList.toggle('maximized',state.layout.maximized===key);
    const maxBtn=card.querySelector('[data-action="maximize"]');
    if(maxBtn){maxBtn.textContent=state.layout.maximized===key?'↙':'⛶';maxBtn.title=state.layout.maximized===key?'Restore four-view layout':`Maximize ${card.querySelector('.view-heading b')?.textContent||key}`}
  }
  const visible=cards.filter(c=>!c.classList.contains('minimized')&&(!state.layout.maximized||c.classList.contains('maximized'))).length;
  if(!state.layout.maximized){
    grid.style.gridTemplateColumns=visible<=1?'1fr':'1fr 1fr';
    grid.style.gridTemplateRows=visible<=2?'1fr':'1fr 1fr';
  }else{grid.style.gridTemplateColumns='1fr';grid.style.gridTemplateRows='1fr'}
  const dock=$("viewDock");dock.innerHTML='';
  for(const key of state.layout.minimized){const card=grid.querySelector(`[data-view="${key}"]`);if(!card)continue;const b=document.createElement('button');b.textContent=`Restore ${card.querySelector('.view-heading b')?.textContent||key}`;b.onclick=()=>{state.layout.minimized.delete(key);refreshViewLayout()};dock.appendChild(b)}
  document.querySelector('.workspace')?.classList.toggle('focus-workspace',state.layout.focusWorkspace);
  if($("focusWorkspaceBtn"))$("focusWorkspaceBtn").textContent=state.layout.focusWorkspace?'Restore panels':'Focus workspace';
  requestAnimationFrame(()=>{renderAnalysisViews();const el=$("potree_render_area");state.viewer?.renderer?.setSize?.(el.clientWidth,el.clientHeight)})
}
export function toggleMaximize(key){state.layout.maximized=state.layout.maximized===key?null:key;if(state.layout.maximized)state.layout.minimized.delete(key);refreshViewLayout()}
export function minimizeView(key){if(state.layout.maximized===key)state.layout.maximized=null;state.layout.minimized.add(key);refreshViewLayout()}

// One-time setup (original statements 100–108); called by app.js in the original order.
export function init() {
  document.querySelectorAll('.view-action').forEach(btn=>btn.onclick=e=>{e.stopPropagation();const key=btn.closest('.view-card')?.dataset.view;if(!key)return;if(btn.dataset.action==='maximize')toggleMaximize(key);else minimizeView(key)});
  $("resetLayoutBtn").onclick=()=>{state.layout.maximized=null;state.layout.minimized.clear();state.layout.focusWorkspace=false;refreshViewLayout();toast('Four-view engineering layout restored.','success')};
  $("focusWorkspaceBtn").onclick=()=>{state.layout.focusWorkspace=!state.layout.focusWorkspace;refreshViewLayout()};
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&state.layout.maximized){state.layout.maximized=null;refreshViewLayout();return}if(['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName))return;const map={"1":"plan","2":"profile","3":"cross","4":"three"};if(map[e.key])toggleMaximize(map[e.key])});
  refreshViewLayout();
  window.addEventListener('resize',()=>{renderAnalysisViews();const el=$("potree_render_area");state.viewer?.renderer?.setSize?.(el.clientWidth,el.clientHeight);const production=$("production_render_area");state.productionViewer?.renderer?.setSize?.(production.clientWidth,production.clientHeight)});
}
