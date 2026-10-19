// Cardinal-direction panning for the Production LiDAR viewer.
import * as THREE from "../../potree/libs/three.js/build/three.module.js";
import { $, state } from "./core.js?v=20261020-session-work3";
import { productionUnitLabel } from "./production-view.js?v=20261020-session-work3";

const DIRECTIONS={north:{x:0,y:1,label:"North",axis:"+Y"},south:{x:0,y:-1,label:"South",axis:"-Y"},east:{x:1,y:0,label:"East",axis:"+X"},west:{x:-1,y:0,label:"West",axis:"-X"}};

export function productionDirectionDistance(){const radius=Number(state.productionViewer?.scene.view.radius)||0,minimum=productionUnitLabel()==="ft"?5:2;return Math.max(minimum,radius*.4)}

export function moveProductionDirection(direction){const v=state.productionViewer,vector=DIRECTIONS[direction];if(!v||!state.productionPointclouds.length||!vector)return;const distance=productionDirectionDistance(),offset=new THREE.Vector3(vector.x*distance,vector.y*distance,0),view=v.scene.view;view.position.add(offset);v.controls?.stop?.();v.orbitControls?.stop?.();const status=$("productionDirectionStatus");if(status){status.textContent=`Moved ${vector.label} ${distance.toFixed(distance<10?1:0)} ${productionUnitLabel()}`;clearTimeout(status._clearTimer);status._clearTimer=setTimeout(()=>{status.textContent=""},1800)}}

export function refreshProductionDirectionAvailability(){const disabled=!state.productionViewer||!state.productionPointclouds.length;document.querySelectorAll("[data-production-direction]").forEach(button=>{button.disabled=disabled})}

export function installProductionDirectionPad(){const pad=document.createElement("div");pad.id="productionDirectionPad";pad.className="production-direction-pad";pad.setAttribute("role","group");pad.setAttribute("aria-label","Move map by cardinal direction");pad.innerHTML='<button type="button" class="direction-north" data-production-direction="north" aria-label="Move map north" title="Move north (+Y)"><span>↑</span><b>N</b></button><button type="button" class="direction-west" data-production-direction="west" aria-label="Move map west" title="Move west (-X)"><span>←</span><b>W</b></button><span class="direction-centre" aria-hidden="true">✦</span><button type="button" class="direction-east" data-production-direction="east" aria-label="Move map east" title="Move east (+X)"><b>E</b><span>→</span></button><button type="button" class="direction-south" data-production-direction="south" aria-label="Move map south" title="Move south (-Y)"><b>S</b><span>↓</span></button><span id="productionDirectionStatus" class="direction-status" role="status" aria-live="polite"></span>';$('productionNavHint').before(pad);pad.addEventListener("click",event=>{const button=event.target.closest("[data-production-direction]");if(button)moveProductionDirection(button.dataset.productionDirection)})}

export function init(){installProductionDirectionPad();refreshProductionDirectionAvailability();document.addEventListener("production-route-data-changed",refreshProductionDirectionAvailability)}
