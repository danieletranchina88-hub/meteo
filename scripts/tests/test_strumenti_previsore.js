'use strict';
// Gli strumenti da previsore: ore in Z e in ora italiana, carte pronte,
// scorciatoie da tastiera, link alla carta, estremi del campo in vista,
// punto di rugiada.
//
// Nessuno di questi aggiunge un dato: cambiano come si arriva a una carta e
// come la si legge. Le prove sorvegliano che restino fedeli a questa regola
// -- un'ora scritta in due fusi e' la stessa ora, un link riapre la stessa
// carta, gli estremi sono letti con la stessa funzione della scheda del
// punto.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const meteogrammi = fs.readFileSync(path.join(root, 'meteograms.html'), 'utf8');
const stile = fs.readFileSync(path.join(root, 'modern-ui.css'), 'utf8');

function implementazione(nome, sorgente) {
  const testo = sorgente || html;
  const inizio = testo.indexOf('      function ' + nome + '(');
  assert.ok(inizio >= 0, 'manca ' + nome);
  return testo.slice(inizio, testo.indexOf('\n      }\n', inizio) + 8);
}

let ok = true;
function prova(nome, fn) {
  try { fn(); console.log('PASS ' + nome); }
  catch (errore) { ok = false; console.log('FALLITO ' + nome + ': ' + errore.message); }
}

function moduloOre(utc) {
  return new Function('let oraUtc = ' + utc + ';'
    + ['fusoAttivo', 'formatClockTime', 'formatDateTime', 'formatAltTime', 'formatRun', 'oreLeggibili']
      .map((n) => implementazione(n)).join('\n')
    + '\nreturn {formatClockTime, formatDateTime, formatAltTime, formatRun, oreLeggibili};')();
}

prova('il run porta il suo nome in Z, in qualunque fuso', () => {
  for (const utc of [false, true]) {
    assert.equal(moduloOre(utc).formatRun({ runTime: '2026-11-09T12:00:00Z' }), 'Run 09 nov · 12Z');
    assert.equal(moduloOre(utc).formatRun({ runTime: '2026-01-05T00:00:00Z' }), 'Run 05 gen · 00Z');
  }
});

prova('la stessa ora si legge in ora italiana e in UTC', () => {
  const istante = new Date('2026-11-10T08:00:00Z');
  const locale = moduloOre(false), utc = moduloOre(true);
  // Novembre: ora solare, UTC+1.
  assert.match(locale.formatDateTime(istante), /mar 10 nov · 09:00$/);
  assert.equal(locale.formatAltTime(istante), '08Z');
  assert.match(utc.formatDateTime(istante), /mar 10 nov · 08:00 UTC$/);
  assert.equal(utc.formatAltTime(istante), '09:00 ora it.');
  // Luglio: ora legale, UTC+2. Il cambio di data a cavallo della mezzanotte
  // deve seguire il fuso scelto.
  const estate = new Date('2026-07-14T22:30:00Z');
  assert.match(locale.formatDateTime(estate), /mer 15 lug · 00:30$/);
  assert.equal(locale.formatAltTime(estate), '22:30Z');
  assert.match(utc.formatDateTime(estate), /mar 14 lug · 22:30 UTC$/);
});

prova('nel bollettino gli istanti ISO e i decimali diventano leggibili', () => {
  const testo = 'Nel periodo centrato su 2026-11-10T08:00:00Z il minimo e\' 1009.5 hPa a 48.04°N.';
  assert.equal(moduloOre(false).oreLeggibili(testo),
    'Nel periodo centrato su mar 10 nov 09:00 (08Z) il minimo e\' 1009,5 hPa a 48,04°N.');
  assert.match(moduloOre(true).oreLeggibili(testo), /mar 10 nov 08:00 UTC \(09:00 ora it\.\)/);
  // Un testo senza istanti non cambia, a parte i decimali.
  assert.equal(moduloOre(false).oreLeggibili('ICON-2I, 73 scadenze'), 'ICON-2I, 73 scadenze');
  assert.match(implementazione('appendBulletinParagraph'), /oreLeggibili\(text\)/,
    'il bollettino mostra ancora gli istanti ISO grezzi');
});

prova('il punto di rugiada segue la formula di Magnus', () => {
  const f = new Function(implementazione('dewPointCelsius') + '\nreturn dewPointCelsius;')();
  assert.ok(Math.abs(f(20, 50) - 9.26) < 0.05, 'Td(20 °C, 50 %) non e\' 9,3 °C');
  assert.ok(Math.abs(f(30, 70) - 23.9) < 0.1, 'Td(30 °C, 70 %) non e\' 23,9 °C');
  assert.ok(Math.abs(f(-5, 100) + 5) < 0.01, 'a saturazione la rugiada non coincide con la temperatura');
  assert.ok(f(15, 60) < 15, 'la rugiada supera la temperatura');
  assert.ok(Number.isNaN(f(NaN, 50)) && Number.isNaN(f(10, NaN)), 'un dato mancante produce un numero');
  assert.match(html, /id="detail-dewpoint"/, 'la scheda del punto non mostra la rugiada');
});

prova('le carte pronte usano solo campi che esistono', () => {
  const tabella = html.match(/const CARTE_PRONTE = \[[\s\S]*?\n      \];/);
  assert.ok(tabella, 'mancano le carte pronte');
  const carte = new Function(tabella[0] + '\nreturn CARTE_PRONTE;')();
  assert.equal(carte.length, 6, 'le carte pronte non sono piu\' sei: i tasti 1-6 non corrispondono');
  for (const carta of carte) {
    assert.ok(html.includes('data-layer="' + carta.campo + '"'), 'la carta ' + carta.id + ' usa un campo senza bottone');
    for (const chiave of ['isobare', 'fronti', 'isoipse']) {
      assert.equal(typeof carta[chiave], 'boolean', carta.id + ': manca ' + chiave);
    }
  }
  // Le particelle seguono il vento a 10 m: sulle carte in quota vanno spente.
  for (const id of ['850', '500']) {
    assert.equal(carte.find((c) => c.id === id).flusso, false, 'la carta ' + id + ' lascia le particelle a 10 m');
  }
  // La carta segnata e' quella che coincide con lo stato, non l'ultima premuta.
  const ctx = { weatherView: 'forecast', synopticChart: false, activeLayer: 'temp',
    showIsobars: true, showIsohypses: false, showFronts: true, CARTE_PRONTE: carte,
    frontiDisponibili: () => true };
  vm.createContext(ctx);
  vm.runInContext(implementazione('cartaAttiva'), ctx);
  assert.equal(ctx.cartaAttiva(), 'suolo');
  ctx.showFronts = false;
  assert.equal(ctx.cartaAttiva(), '', 'spenti i fronti a mano la carta Suolo resta segnata');
  ctx.activeLayer = 'geopot500'; ctx.showIsohypses = true;
  assert.equal(ctx.cartaAttiva(), '500');
  ctx.weatherView = 'satellite';
  assert.equal(ctx.cartaAttiva(), '');
});

prova('la tastiera non ruba i tasti a chi scrive e lascia Alt alla mappa', () => {
  const tasti = implementazione('tastoPrevisore');
  assert.match(tasti, /event\.ctrlKey \|\| event\.metaKey\) return;/, 'le scorciatoie rubano Ctrl/Cmd al browser');
  assert.match(tasti, /tag === "TEXTAREA" \|\| tag === "SELECT"/, 'le scorciatoie scattano nei campi di testo');
  assert.match(tasti, /if \(campoTesto\) return;/);
  assert.match(tasti, /if \(event\.altKey\) \{[\s\S]*?map\.panBy/, 'con Alt le frecce non spostano piu\' la mappa');
  assert.match(tasti, /if \(event\.shiftKey\) saltaOre\(freccia \* 6\);/, 'Maiusc + freccia non salta di sei ore');
  assert.match(tasti, /tag === "BUTTON" \|\| tag === "A" \|\| tag === "SUMMARY"\) return;/,
    'lo spazio su un bottone avvia anche l\'animazione');
  // Ogni tasto di campo punta a un campo vero.
  const campi = new Function(html.match(/const TASTI_CAMPO = \{[^}]+\};/)[0] + '\nreturn TASTI_CAMPO;')();
  for (const campo of Object.values(campi)) {
    assert.ok(html.includes('data-layer="' + campo + '"'), 'tasto verso un campo inesistente: ' + campo);
  }
  // La guida elenca i tasti che esistono davvero.
  for (const tasto of ['Maiusc', 'Spazio', 'Alt']) {
    assert.ok(html.includes('<kbd>' + tasto + '</kbd>'), 'la guida non spiega ' + tasto);
  }
});

prova('i salti contano ore vere, non posizioni', () => {
  const ore = Array.from({ length: 10 }, (_, i) => ({ validTime: new Date(Date.UTC(2026, 10, 10, i * 3)).toISOString() }));
  const visti = [];
  const ctx = { catalog: ore, ui: { slider: { value: '2' } }, Math, Number, Infinity,
    parseCatalogDate: (v) => new Date(v.validTime), vaiAllaScadenza: (i) => visti.push(i) };
  vm.createContext(ctx);
  vm.runInContext(implementazione('indicePerIstante') + implementazione('saltaOre'), ctx);
  // Passo di 3 ore: +6 ore sono due posizioni, non sei.
  ctx.saltaOre(6); ctx.saltaOre(-6);
  assert.deepEqual(visti, [4, 0]);
});

prova('il link riapre la stessa carta e non congela l\'ora di oggi', () => {
  const adesso = Date.UTC(2026, 10, 10, 8);
  const catalogo = Array.from({ length: 24 }, (_, i) => ({ validTime: new Date(adesso + (i - 4) * 3600000).toISOString().replace('.000Z', 'Z') }));
  const ctx = { URLSearchParams, String, Math, Number, Infinity, Date: { now: () => adesso },
    weatherView: 'forecast', activeLayer: 'temp', selectedLevel: 'surface', catalog: catalogo,
    currentIndex: 4, vistaMossa: false, selectedPoint: null,
    map: { getCenter: () => ({ lat: 41.512, lng: 12.987 }), getZoom: () => 6.44 },
    parseCatalogDate: (v) => new Date(v.validTime) };
  vm.createContext(ctx);
  vm.runInContext(implementazione('indicePerIstante') + implementazione('parametriLink'), ctx);
  assert.equal(ctx.parametriLink().toString(), '', 'sulla carta di partenza il link porta parametri inutili');
  ctx.currentIndex = 10; ctx.activeLayer = 'rain'; ctx.vistaMossa = true;
  ctx.selectedPoint = { lat: 41.9, lng: 12.49, title: 'Roma' };
  const p = ctx.parametriLink();
  assert.equal(p.get('campo'), 'rain');
  assert.equal(p.get('ora'), '2026-11-10T14Z');
  assert.equal(p.get('vista'), '41.51,12.99,6.4');
  assert.equal(p.get('lat'), '41.9000');
  assert.equal(p.get('nome'), 'Roma');
  // Il ripristino: un'ora che non e' piu' nel run non viene forzata.
  const ripristino = implementazione('ripristinaDaLink');
  assert.match(ripristino, /< 30 \* 60000/, 'un link vecchio viene forzato sulla scadenza piu\' vicina');
  assert.match(ripristino, /finally \{\s*linkRipristinato = true;/, 'dopo un link sbagliato l\'indirizzo non si aggiorna piu\'');
  assert.match(implementazione('programmaLink'), /if \(!linkRipristinato \|\| linkTimer\) return;/,
    'l\'indirizzo ricevuto viene riscritto prima di essere letto');
});

prova('gli estremi in vista si leggono come la scheda del punto', () => {
  const estremi = implementazione('estremiInVista');
  assert.match(estremi, /fieldValue\(activeLayer, punto\.gx, punto\.gy\)/,
    'gli estremi non usano la lettura della scheda del punto');
  assert.match(estremi, /info\.categorical\) return null/, 'estremi calcolati su un campo a classi');
  // Eseguito davvero: campo a gradiente lineare, estremi ai due bordi.
  const ctx = { Math, Number, Infinity, window: { innerWidth: 900, innerHeight: 600 },
    currentData: {}, activeLayer: 'temp', weatherView: 'forecast',
    map: { unproject: (p) => ({ lng: p[0], lat: p[1] }) },
    activeLayerInfo: () => ({ stops: [{ v: -40 }, { v: 40 }], decimals: 1 }),
    pointFromCoordinates: (lng, lat) => ({ gx: lng, gy: lat }),
    fieldValue: (_, gx) => gx / 900 * 30 };
  vm.createContext(ctx);
  vm.runInContext(implementazione('estremiInVista') + implementazione('posizioneLegenda')
    + 'const clamp = (v, a, b) => Math.max(a, Math.min(b, v));', ctx);
  const r = ctx.estremiInVista();
  assert.ok(r.minimo >= 0 && r.minimo < 1 && r.massimo > 29 && r.massimo <= 30, 'estremi sbagliati: ' + JSON.stringify(r));
  assert.equal(vm.runInContext('posizioneLegenda(0, activeLayerInfo())', ctx), 50);
  assert.equal(vm.runInContext('posizioneLegenda(99, activeLayerInfo())', ctx), 100);
  // Senza abbastanza punti validi non si scrive niente.
  ctx.pointFromCoordinates = () => null;
  assert.equal(ctx.estremiInVista(), null);
});

prova('le tacche della legenda non si accavallano', () => {
  const legenda = implementazione('updateLegend');
  assert.match(legenda, /const ingombro = 2\.2 \* String\(tick\)\.length \+ 1;/,
    'la distanza fra le tacche non segue la lunghezza del numero');
  assert.match(legenda, /programmaStatisticheVista\(\);/, 'cambiando campo gli estremi in vista non si aggiornano');
});

prova('i numeri si scrivono con la virgola', () => {
  const f = new Function(implementazione('formatValue') + '\nreturn formatValue;')();
  assert.equal(f(16.14, 1, '°C'), '16,1 °C');
  assert.equal(f(1016, 0, 'hPa'), '1016 hPa');
  assert.equal(f(42, 0, '/100'), '42/100');
  assert.equal(f(NaN, 1, '°C'), '--');
  assert.match(meteogrammi, /toFixed\(decimals\)\.replace\("\.", ","\)/, 'i meteogrammi scrivono ancora il punto decimale');
});

prova('i meteogrammi hanno icone disegnate e la notte vera', () => {
  const simboli = implementazione('weatherSymbol', meteogrammi);
  assert.doesNotMatch(simboli, /[☀-➿]|[\uD83C-\uD83E]/, 'tornano le emoji fra i simboli del tempo');
  const sole = new Function(implementazione('solarElevation', meteogrammi) + '\nreturn solarElevation;')();
  // Palermo: a mezzogiorno solare di novembre il sole e' a ~35 gradi, al
  // solstizio d'estate a ~75; alle 21 UTC e' notte fonda.
  assert.ok(Math.abs(sole(new Date('2026-11-10T11:10:00Z'), 38.1, 13.36) - 34.7) < 1.5);
  assert.ok(Math.abs(sole(new Date('2026-06-21T11:10:00Z'), 38.1, 13.36) - 75.3) < 1.5);
  assert.ok(sole(new Date('2026-11-10T21:00:00Z'), 38.1, 13.36) < -40);
});

prova('i nuovi comandi hanno il loro stile e non si duplicano', () => {
  for (const selettore of ['#carte-pronte', '#guida-tasti', '.ora-switch', '#legend-sonda', '#legend-vista']) {
    assert.ok(stile.includes(selettore), 'manca lo stile di ' + selettore);
  }
  for (const id of ['carte-pronte', 'guida-tasti', 'time-alt', 'legend-vista', 'legend-sonda']) {
    assert.equal(html.split('id="' + id + '"').length - 1, 1, 'id duplicato o mancante: ' + id);
  }
  assert.match(html, /collegaStrumentiPrevisore\(\);\s*\n\s*resizeCanvases\(\);/, 'gli strumenti non vengono collegati');
});

console.log(ok ? 'ESITO: SUPERATO' : 'ESITO: DA RIVEDERE');
process.exitCode = ok ? 0 : 1;
