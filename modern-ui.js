/* Presentation and frame warming share the existing scientific renderer. */
const warmWorkerState = { terrainKey: '' };
function dispatchWarmRaster(params, onDone) {
  if (warmFrameBusy || typeof Worker === 'undefined') return;
  try {
    if (!warmRasterWorker) {
      // Stesso sorgente del worker che disegna adesso: la correzione di quota
      // vale anche per i fotogrammi scaldati in anticipo, altrimenti la barra
      // del tempo mostrerebbe mappe non corrette a ogni passo gia' in cache.
      const url = URL.createObjectURL(new Blob([rasterWorkerSource()],{type:'application/javascript'}));
      warmRasterWorker = new Worker(url); URL.revokeObjectURL(url);
      warmWorkerState.terrainKey = '';
    }
    warmFrameBusy = true;
    warmRasterWorker.onmessage = function(e) {
      warmFrameBusy = false; onDone(new Uint8ClampedArray(e.data.pixels), e.data.stat); scheduleFrameWarmup();
    };
    warmRasterWorker.onerror = function() {
      warmFrameBusy = false; warmRasterWorker.terminate(); warmRasterWorker = null;
      warmWorkerState.terrainKey = '';
    };
    warmRasterWorker.postMessage(rasterMessage(params, warmWorkerState));
  } catch (_) { warmFrameBusy = false; }
}
let warmedIndices = new Set();
let warmContextKey = '';
function scheduleFrameWarmup() {
  if (warmFrameTimer) return;
  warmFrameTimer = setTimeout(function() {
    warmFrameTimer = null;
    if (!mapLoaded || !currentData || isMapMoving || document.hidden || weatherView !== 'forecast' || showFusion || activeLayer === 'none' || warmFrameBusy) return;
    const bounds = map.getBounds();
    const key = [activeModel,activeLayer,selectedLevel,useNearestCell,window.innerWidth,window.innerHeight,
      bounds.getWest().toFixed(4),bounds.getEast().toFixed(4),bounds.getNorth().toFixed(4),bounds.getSouth().toFixed(4),weatherFrameEpoch].join('|');
    if(key !== warmContextKey) { warmContextKey = key; warmedIndices.clear(); }
    const kind = activeExtraKind();
    const order = catalog.map((_,i)=>i).filter(i=>i !== currentIndex && stepCache.has(i) && !warmedIndices.has(i) &&
      (!kind || extraResources.has(extraKey(i,kind)))).sort((a,b)=>Math.abs(a-currentIndex)-Math.abs(b-currentIndex));
    const index = order[0]; if(index === undefined) return;
    // Capture only. No labels, canvas, source or selected step are changed by prewarming.
    const saved = [currentData,currentIndex,upperData,upperIndex,stormData,stormIndex];
    try {
      currentData = stepCache.get(index); currentIndex = index;
      if(kind === 'upper') { upperData = extraResources.get(extraKey(index,kind)); upperIndex = index; }
      if(kind === 'storm') { stormData = extraResources.get(extraKey(index,kind)); stormIndex = index; }
      renderWeather(true); warmedIndices.add(index);
    } finally { [currentData,currentIndex,upperData,upperIndex,stormData,stormIndex] = saved; }
    if (!warmFrameBusy) scheduleFrameWarmup();
  },100);
}
function setWeatherView(view) {
  if (weatherView === view || !mapLoaded) return;
  if (view === 'satellite') {
    if(synopticChart) setSynopticChart(false);
    forecastRestore = {layer:activeLayer,particles:showParticles,vectors:showVectors,isobars:showIsobars,
      isotherms:showIsotherms,isohypses:showIsohypses,fronts:showFronts,fusion:showFusion,
      stations:showStations,terrain:showTerrain,satellite:showSatellite,threed:show3D,graticule:showGraticule};
    setPlaying(false); ++loadingToken; ++rasterRenderToken; pendingRasterCallback = null;
    weatherView = 'satellite'; clearMeteorologicalLayers();
    show3D = false; showSatellite = false; showSatelliteClouds = true;
    updateTerrain3D(); updateSatelliteBase(); updateSatelliteClouds();
    // I fulmini in diretta sono un livello osservato come il satellite:
    // devono accendersi da soli entrando in questa vista, non aspettare che
    // qualcuno trovi l'interruttore nel pannello. blitzConnect e
    // startStrikeAnimation sono gia' idempotenti (non riaprono un socket o
    // un timer gia' attivi), quindi rientrare in satellite piu' volte non
    // duplica niente.
    showLiveLightning = true;
    blitzRetryDelay = 2000;
    blitzConnect();
    startStrikeAnimation();
  } else {
    // Tornando alla previsione l'osservato torna in diretta: lasciare l'ora
    // scelta avrebbe fatto ricomparire, al rientro, un'immagine vecchia senza
    // che nessuno l'avesse piu' chiesta.
    weatherView = 'forecast'; showSatelliteClouds = false; showLightning = false;
    cloudTimeSelected = 0; updateLightningLayer(); updateSatelliteClouds();
    // Radar e fulmini in diretta sono livelli osservati come il satellite, e
    // il loro comando vive nel pannello del satellite: lasciarli accesi qui
    // vorrebbe dire lasciare sulla previsione un livello che non si puo' piu'
    // spegnere, perche' il pannello non c'e'. Anche la connessione al flusso
    // va chiusa: nessuno la sta piu' guardando.
    showRadar = false;
    if (map.getLayer('radar-layer')) map.setLayoutProperty('radar-layer','visibility','none');
    if (showLiveLightning) { showLiveLightning = false; blitzDisconnect(); stopStrikeAnimation(); liveStrikes = []; }
    // Il ray marcher e' pesante: non ha senso lasciarlo acceso su una vista
    // che non lo mostra piu'.
    if (showVolumeClouds) { showVolumeClouds = false; NubiVolumetriche.disattiva(); }
    const saved = forecastRestore;
    if(saved) {
      activeLayer=saved.layer; showParticles=saved.particles; showVectors=saved.vectors;
      showIsobars=saved.isobars; showIsotherms=saved.isotherms; showIsohypses=saved.isohypses;
      showFronts=saved.fronts; showFusion=saved.fusion; showStations=saved.stations;
      showTerrain=saved.terrain; showSatellite=saved.satellite; show3D=saved.threed; showGraticule=saved.graticule;
    }
    map.setLayoutProperty('weather-layer','visibility',activeLayer === 'none' ? 'none' : 'visible');
    lastRasterSignature=''; updateTerrain3D(); updateSatelliteBase(); updateMapPresentation();
    updateIsobars(); updateStationMarkers(); renderWeather(); requestVectorRender();
    if(showParticles) startParticles();
    updateTimeUi(); updateBufferUi(); scheduleFrameWarmup();
  }
  // Il dominio percorribile si aggiorna QUI, in coda, non dentro i due rami:
  // entrando nella vista satellite showSatelliteClouds viene acceso DOPO
  // clearMeteorologicalLayers(), quindi un aggiornamento piu' in alto
  // leggerebbe i flag a meta' strada e terrebbe la mappa stretta sul dominio
  // del modello -- misurato: minZoom restava 4,52 invece di scendere a 2,80,
  // e l'Atlantico non si raggiungeva.
  aggiornaDominioNavigabile();
  // Le canvas a tutto schermo cambiano risoluzione con la vista: in satellite
  // ci sono sopra solo i fulmini, e sul telefono quella densita' in meno e'
  // la differenza fra 43 e 17 millisecondi a fotogramma.
  resizeCanvases();
  document.body.classList.toggle('satellite-view',view === 'satellite');
  document.getElementById('satellite-status').hidden = view !== 'satellite';
  updateSatelliteControlsVisibility();
  document.getElementById('forecast-view').setAttribute('aria-pressed',String(view === 'forecast'));
  document.getElementById('satellite-view').setAttribute('aria-pressed',String(view === 'satellite'));
  updateLayerUi(); updateLegend(); setDrawer(false);
}
(function modernControls() {
  const rail=document.getElementById('quick-layers');
  const paths={temp:'M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0Z',wind:'M3 8h12a3 3 0 1 0-3-3 M3 12h16a3 3 0 1 1-3 3 M3 16h5',rain:'M5 14a4 4 0 0 1 0-8 6 6 0 0 1 11-1 4.5 4.5 0 0 1 1 9 M8 17l-1 3 M13 17l-1 3 M18 17l-1 3',cloud:'M6 17a5 5 0 0 1 0-10 6 6 0 0 1 11-1 5.5 5.5 0 0 1 0 11Z',press:'M5 19a9 9 0 1 1 14 0 M12 12l4-4 M4 12h2 M18 12h2',rh:'M12 3S5 11 5 15a7 7 0 0 0 14 0c0-4-7-12-7-12Z'};
  ['wind','temp','rain','cloud','press','rh'].forEach(function(key) {
    const button=document.querySelector('[data-layer="'+key+'"]');
    if(!button) return;
    const swatch=button.querySelector('.layer-swatch');
    swatch.innerHTML='<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="'+paths[key]+'"></path></svg>';
    button.title=button.querySelector('b').textContent;
    rail.append(button);
  });
  const advanced=document.createElement('button'); advanced.className='all-fields'; advanced.type='button';
  advanced.innerHTML='<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"></path></svg><span>Altri campi</span>';
  advanced.addEventListener('click',()=>setDrawer(true));rail.append(advanced);
  document.getElementById('forecast-view').addEventListener('click',()=>setWeatherView('forecast'));
  document.getElementById('satellite-view').addEventListener('click',()=>setWeatherView('satellite'));
  const satellitePicker=document.getElementById('satclouds-picker');
  document.getElementById('satellite-controls').append(satellitePicker);
  // Status belongs in the tools menu, not in the logo.
  document.querySelector('.drawer-content').append(document.getElementById('agents-open'));
  const query=document.getElementById('place-query'), results=document.getElementById('place-results');
  query.addEventListener('input',function() {
    results.replaceChildren(); const value=query.value.trim().toLocaleLowerCase('it');
    if(value.length < 2) {results.hidden=true;return;}
    const places=(placeNames || []).filter(p=>p.name.toLocaleLowerCase('it').includes(value)).slice(0,7);
    places.forEach(function(p) {
      const button=document.createElement('button');button.type='button';button.textContent=p.name;
      button.addEventListener('click',function() {
        map.flyTo({center:[p.lon,p.lat],zoom:8,duration:prefersReducedMotion?0:650});
        if(weatherView === 'forecast') showPoint(p.lon,p.lat,p.name);
        query.value=p.name;results.hidden=true;
      });results.append(button);
    });
    if(!places.length) { const label=document.createElement('p');label.textContent=placeNames?'Nessuna località trovata':'Località in caricamento';results.append(label); }
    results.hidden=false;
  });
  query.addEventListener('keydown',function(e) {
    if(e.key === 'Escape') {results.hidden=true;query.blur();}
    if(e.key === 'ArrowDown') {e.preventDefault();results.querySelector('button')?.focus();}
    if(e.key === 'Enter') results.querySelector('button')?.click();
  });
  // The native buttons remain reachable with Tab; arrows also navigate results.
  results.addEventListener('keydown', function(e) {
    const buttons = Array.from(results.querySelectorAll('button'));
    const index = buttons.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const next = index + (e.key === 'ArrowDown' ? 1 : -1);
      if (next < 0) query.focus();
      else buttons[Math.min(next, buttons.length - 1)]?.focus();
    }
    if (e.key === 'Escape') { results.hidden = true; query.focus(); }
  });
  query.setAttribute('aria-controls', 'place-results');
  document.addEventListener('click',e=>{if(!document.getElementById('place-search').contains(e.target))results.hidden=true;});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){prefetchWholeRun(currentIndex);scheduleFrameWarmup();}});
})();

/* Responsive layout moves the existing controls; it never duplicates layers. */
(function consoleControls() {
  const rail = document.getElementById('quick-layers');
  const section = document.createElement('section');
  section.className = 'drawer-section mobile-fields';
  section.innerHTML = '<div class="section-title"><h3>Campi principali</h3></div><div class="mobile-field-grid"></div>';
  document.querySelector('.drawer-content').prepend(section);
  const grid = section.querySelector('.mobile-field-grid');
  const fields = Array.from(rail.querySelectorAll('.layer-card'));
  const mobile = window.matchMedia('(max-width: 959px)');
  function arrange() {
    fields.forEach(button => {
      if (mobile.matches) grid.append(button);
      else rail.insertBefore(button, rail.querySelector('.all-fields'));
    });
  }
  arrange();
  mobile.addEventListener('change', arrange);

  // Le carte pronte stanno accanto alla ricerca finche' c'e' posto; sotto i
  // 1180 px entrano in cima al menu dei livelli. E' lo stesso elemento,
  // spostato: i bottoni non si duplicano.
  const carte = document.getElementById('carte-pronte');
  const stretto = window.matchMedia('(max-width: 1179px)');
  function collocaCarte() {
    if (!carte) return;
    if (stretto.matches) document.querySelector('.drawer-content').prepend(carte);
    else document.body.insertBefore(carte, document.getElementById('guida-tasti'));
  }
  collocaCarte();
  stretto.addEventListener('change', collocaCarte);

  const previous = document.getElementById('time-prev');
  const next = document.getElementById('time-next');
  const now = document.getElementById('time-now');
  function go(index) {
    if (!catalog.length || weatherView !== 'forecast') return;
    setPlaying(false);
    const target = Math.max(0, Math.min(catalog.length - 1, index));
    ui.slider.value = target;
    requestSliderStep(target);
  }
  // Read the requested slider position so rapid clicks can queue the latest step.
  previous.addEventListener('click', () => go(Number(ui.slider.value) - 1));
  next.addEventListener('click', () => go(Number(ui.slider.value) + 1));
  now.addEventListener('click', () => {
    let best = -1, distance = Infinity;
    catalog.forEach((item, index) => {
      const date = parseCatalogDate(item);
      const delta = date ? Math.abs(date.getTime() - Date.now()) : Infinity;
      if (delta < distance) { best = index; distance = delta; }
    });
    if (best >= 0) go(best);
  });
  function syncTimeNavigation() {
    previous.disabled = !catalog.length || currentIndex <= 0;
    next.disabled = !catalog.length || currentIndex >= catalog.length - 1;
    now.disabled = !catalog.some(item => parseCatalogDate(item));
    const current = parseCatalogDate(catalog[currentIndex]);
    const day = date => date?.toLocaleDateString('it-IT', {timeZone: fusoAttivo()});
    const activeDay = day(current);
    document.querySelectorAll('#timeline-days button').forEach(button => {
      const index = Math.round(parseFloat(button.style.left) / 100 * Math.max(1, catalog.length - 1));
      button.setAttribute('aria-current', String(Boolean(activeDay) && day(parseCatalogDate(catalog[index])) === activeDay));
    });
  }
  new MutationObserver(syncTimeNavigation).observe(document.getElementById('time-label'), {childList: true});
  syncTimeNavigation();
  document.querySelectorAll('.speed-controls button').forEach(button => {
    button.setAttribute('aria-pressed', String(button.classList.contains('active')));
    button.addEventListener('click', () => document.querySelectorAll('.speed-controls button').forEach(item => {
      item.setAttribute('aria-pressed', String(item === button));
    }));
  });
})();
