const workbookApiBase=()=>((localStorage.getItem("pla_api_base")||window.PLA_CONFIG?.API_BASE||window.location.origin).replace(/\/$/,""));
const workbookToken=()=>localStorage.getItem("pla_token")||"";
const workbookEscape=value=>String(value??"").replace(/[&<>\'"]/g,character=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[character]));

function installPoleWorkbookEditor(){
  const panel=document.querySelector(".annotation-panel");
  if(!panel||panel.dataset.workbookEditorInstalled)return;
  panel.dataset.workbookEditorInstalled="true";
  const pointHeader=panel.querySelector(".annotation-panel-head");
  const pointForm=document.getElementById("annotationForm");
  const annotationList=document.getElementById("productionAnnotationList");
  const poleSelect=document.getElementById("annotationPoleId");
  const projectSelect=document.getElementById("projectSelect");
  const tabs=document.createElement("div");
  tabs.className="annotation-tabs";
  tabs.setAttribute("role","tablist");
  tabs.setAttribute("aria-label","Production details");
  tabs.innerHTML='<button type="button" role="tab" aria-selected="true" class="annotation-tab active" data-annotation-tab="points">Point Attributes</button><button type="button" role="tab" aria-selected="false" class="annotation-tab" data-annotation-tab="workbook">Workbook Data</button><button type="button" role="tab" aria-selected="false" class="annotation-tab" data-annotation-tab="geojson">GeoJSON Data</button>';
  panel.prepend(tabs);
  const savedHeading=annotationList?.previousElementSibling;
  const view=document.createElement("section");
  view.id="poleWorkbookView";
  view.className="pole-workbook-view hidden";
  view.innerHTML='<div class="annotation-panel-head"><b>Pole workbook</b><small id="poleWorkbookPole">Select an Excel pole</small></div><div id="poleWorkbookBusy" class="pole-workbook-busy hidden" role="status" aria-live="polite"><span class="pole-workbook-spinner" aria-hidden="true"></span><b id="poleWorkbookBusyText">Loading workbook data…</b></div><label class="workbook-pole-label">Search Pole Number or internal_id<input id="workbookPoleSearch" type="search" autocomplete="off" placeholder="Type a Pole Number or internal_id" aria-label="Search workbook poles by Pole Number or internal_id"></label><label class="workbook-pole-label">Pole Number<select id="workbookPoleSelect" aria-label="Select pole workbook data"><option value="">Select a workbook pole</option></select></label><small id="workbookPoleSearchStatus" class="workbook-pole-search-status" aria-live="polite"></small><div class="pole-workbook-toolbar"><span id="poleWorkbookMatch" class="pole-workbook-match" role="status"></span><button type="button" id="downloadPoleWorkbookBtn" class="compact-btn" disabled title="Download the saved updated workbook">Download Excel</button></div><div id="poleWorkbookError" class="pole-workbook-error" role="alert"></div><div id="poleWorkbookSheets" class="pole-workbook-sheets"></div><div class="pole-workbook-footer"><button type="button" id="savePoleWorkbookBtn" class="primary" disabled>Save changes</button></div>';
  panel.append(view);
  const geoView=document.createElement("section");
  geoView.id="poleGeojsonView";
  geoView.className="pole-workbook-view hidden";
  geoView.innerHTML='<div class="annotation-panel-head"><b>GeoJSON data</b><small id="poleGeojsonPole">Select a pole</small></div><div id="poleGeojsonBusy" class="pole-workbook-busy hidden" role="status" aria-live="polite"><span class="pole-workbook-spinner" aria-hidden="true"></span><b>Loading GeoJSON data…</b></div><div id="poleGeojsonError" class="pole-workbook-error" role="alert"></div><div id="poleGeojsonProperties" class="pole-workbook-sheets"></div>';
  panel.append(geoView);
  const stylesheet=document.createElement("link");
  stylesheet.rel="stylesheet";
  stylesheet.href=new URL("./workbook-editor.css?v=20261007-generalized-import-3",import.meta.url).href;
  document.head.append(stylesheet);

  const matchStatus=document.getElementById("poleWorkbookMatch");
  const workbookPole=document.getElementById("workbookPoleSelect");
  const poleSearch=document.getElementById("workbookPoleSearch");
  const poleSearchStatus=document.getElementById("workbookPoleSearchStatus");
  const busyRoot=document.getElementById("poleWorkbookBusy");
  const busyText=document.getElementById("poleWorkbookBusyText");
  const poleLabel=document.getElementById("poleWorkbookPole");
  const sheetsRoot=document.getElementById("poleWorkbookSheets");
  const errorRoot=document.getElementById("poleWorkbookError");
  const saveButton=document.getElementById("savePoleWorkbookBtn");
  const downloadButton=document.getElementById("downloadPoleWorkbookBtn");
  const geoPoleLabel=document.getElementById("poleGeojsonPole");
  const geoBusy=document.getElementById("poleGeojsonBusy");
  const geoError=document.getElementById("poleGeojsonError");
  const geoProperties=document.getElementById("poleGeojsonProperties");
  let active="points";
  let generation=0;
  let snapshot=null;
  let loadedContext=null;
  let busy=false;
  let geoProject="";
  let geoFeatures=[];

  function setTab(name){
    active=name;
    for(const tab of tabs.querySelectorAll("[data-annotation-tab]")){
      const selected=tab.dataset.annotationTab===name;
      tab.classList.toggle("active",selected);
      tab.setAttribute("aria-selected",String(selected));
    }
    const showPoints=name==="points",showWorkbook=name==="workbook",showGeojson=name==="geojson";
    pointHeader?.classList.toggle("hidden",!showPoints);
    pointForm?.classList.toggle("hidden",!showPoints);
    annotationList?.classList.toggle("hidden",!showPoints);
    savedHeading?.classList.toggle("hidden",!showPoints);
    view.classList.toggle("hidden",!showWorkbook);
    geoView.classList.toggle("hidden",!showGeojson);
    if(showWorkbook){syncPoleOptions();loadPoleWorkbook()}
    if(showGeojson)loadPoleGeojson()
  }

  async function request(path,options={}){
    const headers={...(options.headers||{}),Authorization:`Bearer ${workbookToken()}`};
    if(options.body&&!headers["Content-Type"])headers["Content-Type"]="application/json";
    const response=await fetch(`${workbookApiBase()}${path}`,{...options,headers});
    const text=await response.text();
    let data=null;
    try{data=text?JSON.parse(text):null}catch{data=text}
    if(!response.ok)throw new Error(data?.detail||data||`HTTP ${response.status}`);
    return data;
  }

  function updateSaveState(){
    const changed=[...sheetsRoot.querySelectorAll("[data-workbook-cell]")].some(input=>input.value!==input.dataset.original);
    saveButton.disabled=busy||!snapshot?.editable||!changed;
    saveButton.classList.toggle("workbook-dirty",changed);
  }

  function setBusy(message=""){
    busy=Boolean(message);
    busyRoot.classList.toggle("hidden",!busy);
    busyText.textContent=message;
    view.setAttribute("aria-busy",String(busy));
    poleSearch.disabled=busy;
    workbookPole.disabled=busy;
    if(busy){saveButton.disabled=true;downloadButton.disabled=true}
    else{updateSaveState();downloadButton.disabled=!snapshot?.download_available}
  }

  function workbookContext(){
    const projectId=projectSelect?.value||localStorage.getItem("pla_project_id")||"";
    const selectedPole=workbookPole?.value||poleSelect?.value||"";
    return {projectId,selectedPole,key:projectId&&selectedPole?`${projectId}:${selectedPole}`:""};
  }

  function poleSearchText(option){return `${option.textContent||""} ${option.dataset.poleNumber||""}`.toLocaleLowerCase()}

  function syncPoleOptions(){
    if(!poleSelect||!workbookPole)return;
    const selected=poleSelect.value||workbookPole.value;
    const query=poleSearch.value.trim().toLocaleLowerCase();
    const sourceOptions=[...poleSelect.options].slice(1);
    const matches=query?sourceOptions.filter(option=>poleSearchText(option).includes(query)):sourceOptions;
    workbookPole.replaceChildren(new Option(matches.length?"Select a workbook pole":"No matching poles",""));
    for(const source of matches){
      const option=new Option(source.textContent,source.value);
      option.dataset.poleNumber=source.textContent.split(" · ")[0];
      workbookPole.add(option);
    }
    if([...workbookPole.options].some(option=>option.value===selected))workbookPole.value=selected;
    poleSearchStatus.textContent=query?`${matches.length} matching pole${matches.length===1?"":"s"}`:`${sourceOptions.length} poles available`;
  }

  function renderWorkbook(data,contextKey=loadedContext){
    snapshot=data;
    loadedContext=contextKey;
    poleLabel.textContent=`Pole Number ${data.pole_number}`;
    const match=data.geojson_match?.status;
    matchStatus.textContent=match==="MATCHED"?"GeoJSON Pole Number matched":match==="AMBIGUOUS"?"Multiple GeoJSON Pole Number matches": "No exact GeoJSON Pole Number match";
    matchStatus.className=`pole-workbook-match ${match=== "MATCHED"?"matched":"unmatched"}`;
    downloadButton.disabled=!data.download_available;
    const editable=Boolean(data.editable);
    sheetsRoot.innerHTML=(data.worksheets||[]).map(sheet=>`<section class="workbook-sheet"><h3>${workbookEscape(sheet.name)}</h3>${sheet.rows.map(row=>`<fieldset class="workbook-row"><legend>Excel row ${row.row}</legend><div class="workbook-fields">${sheet.headers.map((header,index)=>{const column=sheet.columns[index],keyColumn=column===sheet.pole_number_column||(!data.internal_id_editable&&(sheet.internal_id_columns||[]).includes(column)),value=row.values[index],valueText=String(value??"");return `<label class="workbook-field"><span>${workbookEscape(header)}</span><input type="text" value="${workbookEscape(valueText)}" data-workbook-cell data-sheet="${workbookEscape(sheet.name)}" data-row="${row.row}" data-column="${column}" data-original="${workbookEscape(valueText)}" aria-label="${workbookEscape(sheet.name)} row ${row.row}, ${workbookEscape(header)}" ${keyColumn?"readonly":""} ${!editable?"disabled":""}></label>`}).join("")}</div></fieldset>`).join("")}</section>`).join("");
    if(!sheetsRoot.innerHTML)sheetsRoot.innerHTML='<div class="empty-workflow">No worksheet rows match this Pole Number.</div>';
    if(!editable&&match==="MATCHED")matchStatus.textContent="Workbook is available read-only for this role or version";
    sheetsRoot.querySelectorAll("[data-workbook-cell]").forEach(input=>input.addEventListener("input",updateSaveState));
    updateSaveState();
  }

  async function loadPoleWorkbook({force=false}={}){
    const {selectedPole,projectId,key}=workbookContext();
    if(!force&&snapshot&&key&&loadedContext===key){updateSaveState();return}
    const requestGeneration=++generation;
    snapshot=null;
    loadedContext=null;
    saveButton.disabled=true;
    downloadButton.disabled=true;
    sheetsRoot.replaceChildren();
    errorRoot.textContent="";
    if(!selectedPole||!projectId){poleLabel.textContent="Select an Excel pole";matchStatus.textContent="";setBusy();return}
    poleLabel.textContent="Loading workbook rows…";
    setBusy("Loading workbook data…");
    try{
      const data=await request(`/api/projects/${encodeURIComponent(projectId)}/poles/${encodeURIComponent(selectedPole)}/workbook`);
      if(requestGeneration!==generation||key!==workbookContext().key)return;
      renderWorkbook(data,key);
    }catch(error){
      if(requestGeneration!==generation)return;
      poleLabel.textContent=`Pole ID ${selectedPole}`;
      matchStatus.textContent="Workbook data unavailable";
      errorRoot.textContent=error.message;
    }finally{
      if(requestGeneration===generation)setBusy();
    }
  }

  function renderPoleGeojson(selectedPole){
    const matches=geoFeatures.filter(feature=>String(feature.pole_internal_id??"")===String(selectedPole));
    geoPoleLabel.textContent=selectedPole?`Pole ID ${selectedPole}`:"Select a pole";
    if(!selectedPole){geoProperties.innerHTML='<div class="empty-workflow">Choose a pole to see its matched GeoJSON fields.</div>';return}
    if(!matches.length){geoProperties.innerHTML='<div class="empty-workflow">No GeoJSON Point is matched to this pole.</div>';return}
    geoProperties.innerHTML=matches.map(feature=>{const coordinates=feature.source_geometry?.coordinates||[],fields=[['Feature index',feature.feature_index],['Match method',feature.match_method],['Match property',feature.match_property],['Source CRS',feature.source_crs],['Source X / longitude',coordinates[0]],['Source Y / latitude',coordinates[1]],['Source Z',coordinates[2]],...Object.entries(feature.properties||{})];return `<section class="workbook-sheet"><h3>GeoJSON feature ${feature.feature_index}</h3><div class="workbook-fields">${fields.map(([name,value])=>`<label class="workbook-field"><span>${workbookEscape(name)}</span><input type="text" readonly value="${workbookEscape(value!==null&&typeof value==="object"?JSON.stringify(value):value??"")}"></label>`).join("")}</div></section>`}).join("");
  }

  async function loadPoleGeojson({force=false}={}){
    const projectId=projectSelect?.value||localStorage.getItem("pla_project_id")||"",selectedPole=poleSelect?.value||"";
    geoError.textContent="";
    if(!projectId){renderPoleGeojson("");return}
    geoBusy.classList.remove("hidden");
    try{
      if(force||geoProject!==projectId){geoFeatures=await request(`/api/projects/${encodeURIComponent(projectId)}/production-geo-features`);geoProject=projectId}
      renderPoleGeojson(selectedPole);
    }catch(error){geoError.textContent=error.message;geoProperties.replaceChildren()}
    finally{geoBusy.classList.add("hidden")}
  }

  tabs.addEventListener("click",event=>{
    const tab=event.target.closest("[data-annotation-tab]");
    if(tab)setTab(tab.dataset.annotationTab);
  });
  workbookPole.addEventListener("change",()=>{
    if(poleSelect&&poleSelect.value!==workbookPole.value){poleSelect.value=workbookPole.value;poleSelect.dispatchEvent(new Event("change",{bubbles:true}))}
    loadPoleWorkbook();
  });
  poleSearch.addEventListener("input",syncPoleOptions);
  poleSearch.addEventListener("keydown",event=>{
    if(event.key!=="Enter")return;
    event.preventDefault();
    const first=workbookPole.options[1];
    if(first){workbookPole.value=first.value;workbookPole.dispatchEvent(new Event("change",{bubbles:true}))}
  });
  poleSelect?.addEventListener("change",()=>{if(active==="workbook"){poleSearch.value="";syncPoleOptions();loadPoleWorkbook()}else if(active==="geojson")loadPoleGeojson()});
  projectSelect?.addEventListener("change",()=>{geoProject="";geoFeatures=[];if(active==="workbook")setTimeout(loadPoleWorkbook,0);else if(active==="geojson")setTimeout(()=>loadPoleGeojson({force:true}),0)});
  poleSelect&&new MutationObserver(()=>{syncPoleOptions();if(active==="workbook")setTimeout(loadPoleWorkbook,0);else if(active==="geojson")setTimeout(loadPoleGeojson,0)}).observe(poleSelect,{childList:true});
  syncPoleOptions();
  sheetsRoot.addEventListener("input",updateSaveState);

  saveButton.addEventListener("click",async()=>{
    if(!snapshot?.editable)return;
    const updates=[...sheetsRoot.querySelectorAll("[data-workbook-cell]")].filter(input=>input.value!==input.dataset.original).map(input=>({
      sheet:input.dataset.sheet,row:Number(input.dataset.row),column:Number(input.dataset.column),value:input.value,
    }));
    if(!updates.length)return;
    const context=workbookContext();
    setBusy("Saving workbook changes…");
    errorRoot.textContent="";
    try{
      const projectId=context.projectId;
      const poleId=context.selectedPole;
      const data=await request(`/api/projects/${encodeURIComponent(projectId)}/poles/${encodeURIComponent(poleId)}/workbook`,{
        method:"PUT",body:JSON.stringify({snapshot_file_id:snapshot.snapshot_file_id,updates}),
      });
      if(context.key===workbookContext().key){renderWorkbook(data,context.key);matchStatus.textContent="Workbook changes saved"}
      else{snapshot=null;loadedContext=null;if(active==="workbook")setTimeout(loadPoleWorkbook,0)}
    }catch(error){
      errorRoot.textContent=error.message;
    }finally{setBusy()}
  });

  downloadButton.addEventListener("click",async()=>{
    if(!snapshot?.download_available)return;
    downloadButton.disabled=true;
    errorRoot.textContent="";
    try{
      const projectId=projectSelect?.value||localStorage.getItem("pla_project_id");
      const poleId=poleSelect.value;
      const response=await fetch(`${workbookApiBase()}/api/projects/${encodeURIComponent(projectId)}/poles/${encodeURIComponent(poleId)}/workbook-download`,{
        headers:{Authorization:`Bearer ${workbookToken()}`},
      });
      if(!response.ok){const text=await response.text();let error;try{error=JSON.parse(text)}catch{error=text}throw new Error(error?.detail||error||`HTTP ${response.status}`)}
      const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement("a");
      const disposition=response.headers.get("Content-Disposition")||"",matchedName=disposition.match(/filename="?([^";]+)"?/i);
      link.href=url;link.download=matchedName?.[1]||"updated-workbook.xlsx";link.click();URL.revokeObjectURL(url);
    }catch(error){errorRoot.textContent=error.message}
    finally{downloadButton.disabled=!snapshot?.download_available}
  });
}

if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",installPoleWorkbookEditor,{once:true});
else installPoleWorkbookEditor();
