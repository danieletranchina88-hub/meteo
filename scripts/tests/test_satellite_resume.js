'use strict';
// Riprendere la scheda in background non deve mostrare un'immagine vecchia.
//
// loadSatelliteClouds e loadLightning catturano il riquadro e l'istante in
// una chiusura al momento della richiesta, e la pubblicano quando l'Image()
// arriva -- un passo asincrono. Se lo schermo si spegne mentre una di queste
// richieste e' in volo, resta in volo: il browser puo' lasciarla completare
// ore dopo. Le due funzioni si rifiutano di PARTIRNE una nuova mentre
// document.hidden e' vero, ma questo non invalidava una richiesta gia'
// avviata prima: il suo onload confrontava il token con cloudToken/
// lightningToken, che restava fermo per tutto il tempo nascosto, quindi la
// vedeva ancora valida. Riaprendo il telefono si poteva vedere pubblicata
// un'immagine di ore prima -- magari di notte -- sul riquadro di quando lo
// schermo si era spento, sopra la mappa di base per il resto della vista.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

function estraiListener() {
  const inizio = html.indexOf('document.addEventListener("visibilitychange"');
  assert.ok(inizio >= 0, 'manca il listener di visibilitychange');
  const fine = html.indexOf('\n      });', inizio);
  assert.ok(fine >= 0, 'il listener di visibilitychange non si chiude come atteso');
  return html.slice(inizio, fine + 10);
}

let ok = true;
function prova(nome, fn) {
  try { fn(); console.log('PASS ' + nome); }
  catch (error) { ok = false; console.log('FALLITO ' + nome + ': ' + error.message); }
}

prova('riprendendo la scheda il satellite e il Lightning Imager si ricaricano davvero', () => {
  const listener = estraiListener();
  const rami = listener.split('} else {');
  assert.equal(rami.length, 2, 'il listener non ha piu\' i due rami nascosto/visibile');
  const ramoVisibile = rami[1];

  assert.match(ramoVisibile, /loadSatelliteClouds\(true\)/,
    'tornando visibile non si forza un ricarico del satellite: una richiesta ' +
    'vecchia rimasta in volo durante il background resterebbe valida');
  assert.match(ramoVisibile, /if \(showLightning\) loadLightning\(true\)/,
    'tornando visibile non si forza un ricarico del Lightning Imager');
  assert.match(ramoVisibile, /if \(showRadar\) syncRadarToSatellite\(cloudSlot\(\)\)/,
    'tornando visibile il radar non si riallinea al satellite corrente');

  // Il ramo NASCOSTO non deve toccare satellite/lightning: chiuderli o
  // ricaricarli mentre nessuno guarda sprecherebbe soltanto rete.
  const ramoNascosto = rami[0];
  assert.doesNotMatch(ramoNascosto, /loadSatelliteClouds|loadLightning|syncRadarToSatellite/,
    'il ramo nascosto tocca satellite/lightning/radar: dovrebbe limitarsi a fermare fulmini e particelle');
});

prova('il ricarico forzato ignora la cache e riparte da un token nuovo', () => {
  // force=true deve saltare il controllo "serve davvero ricaricare?": e'
  // esattamente il punto, perche' senza forzare, un riquadro/istante che
  // sembra invariato (perche' letto da uno stato ormai vecchio) non
  // ripartirebbe affatto.
  const re = new RegExp('      function loadSatelliteClouds\\(');
  const inizioCloud = html.search(re);
  assert.ok(inizioCloud >= 0, 'manca loadSatelliteClouds');
  const cloud = html.slice(inizioCloud, html.indexOf('\n      }', inizioCloud) + 8);
  assert.match(cloud, /if \(!force && !cloudNeedsReload/,
    'loadSatelliteClouds(true) non salta piu\' il controllo di necessita\'');
  assert.match(cloud, /const token = \+\+cloudToken;/,
    'loadSatelliteClouds non avanza piu\' il token: una richiesta vecchia in volo resterebbe valida');

  const reLight = new RegExp('      function loadLightning\\(');
  const inizioLight = html.search(reLight);
  assert.ok(inizioLight >= 0, 'manca loadLightning');
  const lightning = html.slice(inizioLight, html.indexOf('\n      }', inizioLight) + 8);
  assert.match(lightning, /if \(!force && !lightningNeedsReload/,
    'loadLightning(true) non salta piu\' il controllo di necessita\'');
  assert.match(lightning, /const token = \+\+lightningToken;/,
    'loadLightning non avanza piu\' il token: una richiesta vecchia in volo resterebbe valida');
});

function implementazione(nome) {
  const re = new RegExp('      function ' + nome + '\\(');
  const inizio = html.search(re);
  assert.ok(inizio >= 0, 'manca ' + nome);
  return html.slice(inizio, html.indexOf('\n      }', inizio) + 8);
}

prova('ogni richiesta porta un istante preciso: mai piu\' il mosaico', () => {
  // Il satellite si vedeva a scacchi: riquadri diurni accanto a riquadri
  // notturni con le luci delle citta'. Non era il disegno, era la richiesta.
  // Questo WMS serve un MOSAICO di granuli, ognuno con il suo istante:
  // omettendo &time= -- che e' come si diceva "dammi l'ultima disponibile" --
  // il servizio non ne sceglie uno, compone ogni granulo con quello che ha,
  // e granuli diversi vengono da passaggi diversi. Verificato chiedendo lo
  // stesso riquadro con e senza istante: senza, a scacchi; con, coerente.
  const wms = html.match(/const CLOUD_WMS = "[^"]+";/);
  assert.ok(wms, 'manca CLOUD_WMS');
  const codice = [wms[0], implementazione('mercatorMetresX'),
    implementazione('mercatorMetresY'), implementazione('cloudUrl')].join('\n\n');
  const modulo = new Function(codice + '\nreturn {cloudUrl};')();
  const box = { west: 12, east: 13, south: 37, north: 38 };
  const size = { width: 512, height: 384 };
  const slot = { iso: '2026-09-20T12:00:00.000Z' };

  const composito = modulo.cloudUrl(box, size,
    { layer: 'mtg_fd:rgb_geocolour', mode: 'scene' }, slot);
  const fulmini = modulo.cloudUrl(box, size, { layer: 'mtg_fd:li_afa' }, slot);
  for (const coppia of [['composito', composito], ['fulmini', fulmini]]) {
    assert.match(coppia[1], /&time=2026-09-20T12:00:00\.000Z/,
      'la richiesta ' + coppia[0] + ' non porta piu\' l\'istante: il servizio '
      + 'ricomporrebbe granuli di passaggi diversi nella stessa immagine');
  }
  // Nessun residuo del vecchio ripiego "senza istante, con un numero che
  // cambia": serviva a sfuggire alla cache, e adesso ci pensa l'istante.
  assert.doesNotMatch(composito, /[?&]_=/,
    'e\' tornato il numero anti-cache: significa che si chiede senza istante');

  // Il formato: i compositi RGB non hanno il canale alfa (letto
  // dall'intestazione del PNG che il servizio restituisce: tre canali),
  // quindi il JPEG non perde niente e pesa quindici volte meno -- 217 kB
  // contro 3,1 MB sul riquadro di un telefono. Il Lightning Imager invece e'
  // RGBA e sta SOPRA le nubi: senza trasparenza le coprirebbe.
  assert.match(composito, /&format=image\/jpeg/,
    'i compositi opachi tornano in PNG: quindici volte piu\' byte per niente');
  assert.doesNotMatch(composito, /transparent=true/,
    'si chiede ancora la trasparenza su un formato che non ce l\'ha');
  assert.match(fulmini, /&format=image\/png&transparent=true/,
    'i fulmini perdono la trasparenza: coprirebbero le nubi invece di starci sopra');
});

prova('l\'istante in diretta e\' quello che il servizio dichiara, non una stima', () => {
  // Indovinare l'istante dalla latenza media porta a chiederne uno che non
  // esiste -- misurato sulla pagina vera: 09:40 e 09:30 rifiutati con 502,
  // mentre il servizio dichiarava 08:00. E il ripiego di allora, chiedere
  // senza istante, e' proprio cio' che produceva il mosaico.
  const slot = implementazione('cloudSlot');
  assert.match(slot, /const dichiarato = ultimoIstanteDichiarato\(selected\);/,
    'l\'istante in diretta non viene piu\' dalla dichiarazione del servizio');
  assert.match(slot, /const newest = dichiarato\s*\n\s*\? Math\.floor\(dichiarato \/ slotMs\) \* slotMs/,
    'la dichiarazione non ha piu\' la precedenza sulla stima per latenza');
  // La rilettura della dichiarazione non deve finire in cache: altrimenti
  // l'ultimo istante non avanza mai e la diretta si blocca -- lo stesso
  // tranello di prima, un piano piu' in alto.
  const caps = implementazione('aggiornaIstantiDisponibili');
  assert.match(caps, /CLOUD_CAPS_URL \+ "&_=" \+ adesso/,
    'la rilettura della dichiarazione puo\' arrivare dalla cache: la diretta si fermerebbe');
  assert.match(caps, /adesso - cloudCapsAt < CLOUD_CAPS_TTL_MS/,
    'la dichiarazione viene riletta a ogni giro invece che a intervalli');
  // Ogni prodotto ha il SUO istante: misurato, le nubi dichiaravano 08:00 e
  // il Lightning Imager 09:50. Tenerne uno solo ne sprecherebbe uno.
  assert.match(caps, /cloudCapsEnd\.set\(nome, fine\)/,
    'la dichiarazione non viene piu\' tenuta per singolo prodotto');
  // Quando l'istante non c'e', si arretra di un passo per volta restando
  // sempre su un istante preciso.
  const nubi = implementazione('loadSatelliteClouds');
  assert.match(nubi, /slotArretrato\(product, slot, 1\)/,
    'il ripiego non arretra piu\' di un passo: chiedendo senza istante torna il mosaico');
  assert.doesNotMatch(nubi, /slot\.latest = true/,
    'e\' tornato il ripiego "ultimo disponibile senza istante", che produce il mosaico');
  // E quando la dichiarazione arriva DOPO che il tentativo e' partito con la
  // stima, si salta direttamente all'istante dichiarato invece di scendere
  // passo per passo. Senza, la stima puo' essere avanti di un'ora e mezza e
  // i tentativi finiscono prima di arrivarci: misurato sulla pagina vera,
  // cinque 502 di fila e satellite mai comparso.
  assert.match(nubi, /const dichiarato = ultimoIstanteDichiarato\(product\);\s*\n\s*slot = \(dichiarato && dichiarato < slot\.value\)\s*\n\s*\? cloudSlot\(product\)/,
    'il ripiego non salta all\'istante dichiarato quando questo arriva a tentativo avviato');
});

prova('a scala europea non si scarica piu\' di quanto lo schermo possa mostrare', () => {
  // Allargando l'osservato all'Europa il dettaglio nativo dello strumento
  // vale oltre 9000 pixel, quindi si finiva sempre contro il tetto di 4096:
  // misurato sul servizio vero, 23 MB per fotogramma. Su un telefono in 4G
  // e' una richiesta ogni pochi minuti che non si puo' chiedere a nessuno.
  // Il tetto nuovo guarda quanti pixel lo schermo puo' davvero mostrare.
  const dom = html.match(/const CLOUD_DOMAIN = \{[^}]+\};/);
  assert.ok(dom, 'manca CLOUD_DOMAIN');
  const mod = html.match(/const MODEL_DOMAIN = \{[^}]+\};/);
  const lato = html.match(/const CLOUD_MAX_SIDE = \d+;/);
  const codice = [dom[0], mod[0], lato[0], implementazione('mercatorMetresX'),
    implementazione('mercatorMetresY'), implementazione('cloudRequestSize')].join('\n\n');

  const costruisci = (larghezzaCss, densita) => new Function(
    'document', 'window', 'navigator',
    codice + '\nreturn {cloudRequestSize, CLOUD_DOMAIN, MODEL_DOMAIN,'
      + ' mercatorMetresX, CLOUD_MAX_SIDE};')(
      { getElementById: () => ({ clientWidth: larghezzaCss }) },
      { innerWidth: larghezzaCss, devicePixelRatio: densita },
      { deviceMemory: 8 });

  const prodotto = { metres: 1000 };
  const telefono = costruisci(400, 3);
  const grande = telefono.cloudRequestSize(telefono.CLOUD_DOMAIN, prodotto);
  // La densita' si ferma a 2: sopra, l'occhio non ci arriva e i byte si
  // raddoppiano per niente.
  assert.ok(grande.width <= 400 * 2 * 1.5 + 1,
    'su un telefono il riquadro europeo chiede ancora ' + grande.width + ' pixel di larghezza');
  assert.ok(grande.width * grande.height < 2.5e6,
    'il fotogramma europeo pesa ancora ' + (grande.width * grande.height / 1e6).toFixed(1)
    + ' megapixel su un telefono');

  // Ma il tetto non deve mordere dove il dettaglio serve davvero: su uno
  // schermo grande e sul dominio del modello comanda ancora lo strumento.
  const grosso = costruisci(1600, 2);
  const italia = grosso.cloudRequestSize(grosso.MODEL_DOMAIN, prodotto);
  // Non "sta sotto il tetto" -- quello lo soddisfa anche un tetto assurdo,
  // ed e' il buco che questa prova aveva prima: deve COINCIDERE con il
  // dettaglio nativo dello strumento, cioe' essere lo strumento a comandare.
  const nativo = Math.ceil(
    (grosso.mercatorMetresX(grosso.MODEL_DOMAIN.east)
      - grosso.mercatorMetresX(grosso.MODEL_DOMAIN.west)) / prodotto.metres);
  assert.equal(italia.width, Math.min(nativo, grosso.CLOUD_MAX_SIDE),
    'su uno schermo grande il dominio del modello non arriva piu\' al dettaglio '
    + 'nativo dello strumento: chiede ' + italia.width + ' invece di ' + nativo);

  // E zoomando su una cella il riquadro resta piccolo: li' lo strumento ha
  // davvero pochi campioni, non e' il tetto a limitare.
  const cella = telefono.cloudRequestSize(
    { west: 14, east: 15, south: 37, north: 38 }, prodotto);
  assert.ok(cella.width <= 600,
    'zoomando su una cella si chiedono ' + cella.width + ' pixel per un centinaio di campioni');
});


// Execute the real loader: source-only assertions cannot catch a ReferenceError
// before the first request (the regression introduced by the second cache).
// Il caricatore scarica con scaricaImmagineSatellite (fetch del file, URL
// locale alla mappa): qui la si sostituisce con promesse che la prova
// risolve a mano, una per richiesta. I tasselli nitidi si registrano soltanto.
function ambienteSatellite() {
  const vm = require('node:vm');
  const richieste = [], pubblicazioni = [], aggiornamenti = [], revocati = [], tasselli = [];
  const product = { layer: 'mtg-geocolour' };
  const slot = { value: 123000, date: new Date(123000), latest: false };
  const box = { west: 10, east: 20, south: 35, north: 45 };
  const size = { width: 1800, height: 1200, metres: 2000 };
  const source = { updateImage: frame => aggiornamenti.push(frame) };
  let n = 0;
  const ctx = {
    console, window: {}, mapLoaded: true, showSatelliteClouds: true,
    document: { hidden: false }, cloudProduct: 'geocolour',
    CLOUD_PRODUCTS: { geocolour: product }, cloudToken: 0,
    CLOUD_MAX_PASSI_INDIETRO: 2, cloudFrames: new Map(),
    showRadar: false, cloudPublishedKey: '',
    URL: { revokeObjectURL: u => revocati.push(u) },
    setTimeout: fn => fn(),
    map: { getSource: () => source, setPaintProperty: () => {} },
    aggiornaIstantiDisponibili: () => Promise.resolve(),
    cloudSlot: () => slot, cloudRequestBox: () => box,
    misuraSatellite: () => size, cloudNeedsReload: () => true,
    aggiornaTasselli: (p, t) => tasselli.push([p.layer, t.value]),
    cloudFrameKey: (p, t, b, z) => [p.layer, t.value, b.west, z.width].join('|'),
    cloudUrl: (b, z, p, t) => 'https://sat.example/' + p.layer + '/' + t.value + '?w=' + z.width,
    ultimoIstanteDichiarato: () => 0,
    slotArretrato: (p, t) => ({ ...t, value: t.value - 1000 }),
    publishSatelliteClouds: (...args) => pubblicazioni.push(args),
    markCloudFreshness: () => {}, syncRadarToSatellite: () => {},
    syncTimelineToSatellite: () => {}, toast: () => {},
    scaricaImmagineSatellite: url => new Promise((risolvi, rifiuta) => {
      const r = { url, locale: 'blob:' + (++n) };
      r.arriva = () => { risolvi({ image: { url }, url: r.locale }); return attendi(); };
      r.fallisce = () => { rifiuta(new Error('502')); return attendi(); };
      richieste.push(r);
    })
  };
  vm.createContext(ctx);
  vm.runInContext(implementazione('pubblicaFotogrammaInCache'), ctx);
  vm.runInContext(implementazione('loadSatelliteClouds'), ctx);
  return { ctx, richieste, pubblicazioni, aggiornamenti, revocati, tasselli, product, slot, box, size };
}
const attendi = () => new Promise(r => setImmediate(r));
const nitide = a => a.richieste.filter(r => /w=1800$/.test(r.url));
const asincrone = [];
function provaAsync(nome, fn) {
  asincrone.push(fn().then(() => console.log('PASS ' + nome),
    error => { ok = false; console.log('FALLITO ' + nome + ': ' + error.message); }));
}

provaAsync('il loader parte senza moduli aggiuntivi e pubblica il satellite richiesto', async () => {
  const a = ambienteSatellite();
  a.ctx.loadSatelliteClouds(false);
  assert.equal(nitide(a).length, 1);
  assert.match(nitide(a)[0].url, /mtg-geocolour\/123000\?w=1800$/);
  await nitide(a)[0].arriva();
  assert.equal(a.pubblicazioni.length, 1);
  assert.equal(a.pubblicazioni[0][3], a.product);
  assert.equal(a.pubblicazioni[0][4], a.slot);
  // L'URL locale del file va alla mappa cosi' com'e': niente ricodifica.
  assert.equal(a.pubblicazioni[0][5], nitide(a)[0].locale);
});

provaAsync('i tasselli nitidi partono con l\'immagine di base, sullo stesso istante', async () => {
  const a = ambienteSatellite();
  a.ctx.loadSatelliteClouds(false);
  assert.deepEqual(a.tasselli, [['mtg-geocolour', 123000]],
    'i tasselli non partono insieme all\'immagine di base');
  assert.equal(a.richieste.length, 1, 'oltre ai tasselli parte una sola immagine');
});

provaAsync('i tasselli: istante nell\'URL, vecchi nascosti subito, nuovi solo a cursore fermo', async () => {
  const vm = require('node:vm');
  const wms = html.match(/const CLOUD_WMS = "[^"]+";/)[0];
  const costanti = html.match(/const SAT_TASSELLI = [\s\S]*?let tasselliTimer = 0;/)[0];
  const timers = [];
  const visibilita = [], setTiles = [];
  let sorgente = null;
  const ctx = {
    window: { devicePixelRatio: 1 },
    CLOUD_DOMAIN: { west: -40, south: 26, east: 42, north: 68 },
    setTimeout: fn => { timers.push(fn); return timers.length; },
    clearTimeout: () => {},
    map: {
      getLayer: id => id === 'satellite-clouds-layer' || (id === 'satellite-tasselli-layer' && !!sorgente),
      getSource: id => (id === 'satellite-tasselli' ? sorgente : null),
      addSource: (id, def) => { sorgente = { def, setTiles: t => setTiles.push(t[0]) }; },
      addLayer: () => {},
      getStyle: () => ({ layers: [{ id: 'satellite-clouds-layer' }, { id: 'satellite-lightning-layer' }] }),
      getLayoutProperty: () => 'visible',
      setLayoutProperty: (id, k, v) => visibilita.push(v)
    }
  };
  vm.createContext(ctx);
  vm.runInContext([wms, costanti, implementazione('urlTasselli'), implementazione('preparaTasselli'),
    implementazione('visibilitaTasselli'), implementazione('aggiornaTasselli')].join('\n'), ctx);
  const prodotto = { layer: 'mtg_fd:rgb_geocolour', mode: 'scene' };
  const t1 = { value: 1, iso: '2026-10-16T18:30:00.000Z' };
  const t2 = { value: 2, iso: '2026-10-16T18:40:00.000Z' };
  ctx.aggiornaTasselli(prodotto, t1);
  const url1 = sorgente.def.tiles[0];
  assert.match(url1, /&bbox=\{bbox-epsg-3857\}&width=512&height=512&time=2026-10-16T18:30:00\.000Z$/);
  assert.match(url1, /format=image\/jpeg/);
  timers.shift()();
  assert.equal(visibilita[visibilita.length - 1], 'visible');
  ctx.aggiornaTasselli(prodotto, t2);
  assert.equal(visibilita[visibilita.length - 1], 'none',
    'cambiando istante i tasselli vecchi restano sopra l\'immagine nuova');
  assert.equal(setTiles.length, 0, 'i tasselli nuovi partono prima che il cursore si fermi');
  timers.shift()();
  assert.match(setTiles[0], /time=2026-10-16T18:40:00\.000Z$/);
  assert.equal(visibilita[visibilita.length - 1], 'visible');
  ctx.window.devicePixelRatio = 2;
  assert.match(ctx.urlTasselli(prodotto, t2), /width=768&height=768/,
    'sugli schermi ad alta densita\' il tassello va chiesto a 768 px');
});

prova('sotto i tasselli l\'immagine di base e\' a un terzo della risoluzione', () => {
  const vm = require('node:vm');
  const ctx = { showCloudNowcast: false, LIGHTNING_PRODUCT: { layer: 'li' },
    cloudRequestSize: () => ({ width: 2160, height: 1428, metres: 2000 }) };
  vm.createContext(ctx);
  vm.runInContext(implementazione('misuraSatellite'), ctx);
  const base = ctx.misuraSatellite({}, { layer: 'x' });
  assert.equal(base.width, 720);
  assert.equal(base.height, 476);
  assert.equal(base.metres, 6000);
  assert.equal(ctx.misuraSatellite({}, ctx.LIGHTNING_PRODUCT).width, 2160, 'i fulmini non hanno tasselli');
  ctx.showCloudNowcast = true;
  assert.equal(ctx.misuraSatellite({}, { layer: 'x' }).width, 2160, 'il nowcast lavora sui pixel pieni');
});

provaAsync('satellite spento, mappa non pronta o scheda nascosta non chiedono immagini', async () => {
  for (const caso of ['spento', 'mappa', 'nascosto', 'sorgente']) {
    const a = ambienteSatellite();
    if (caso === 'spento') a.ctx.showSatelliteClouds = false;
    if (caso === 'mappa') a.ctx.mapLoaded = false;
    if (caso === 'nascosto') a.ctx.document.hidden = true;
    if (caso === 'sorgente') a.ctx.map.getSource = () => null;
    a.ctx.loadSatelliteClouds(true);
    assert.equal(a.richieste.length, 0, caso);
    assert.equal(a.ctx.cloudToken, 0, caso);
  }
});

provaAsync('il ricarico forzato sostituisce la richiesta in volo anche con cache piena', async () => {
  const a = ambienteSatellite();
  a.ctx.loadSatelliteClouds(false);
  const vecchia = nitide(a)[0];
  const key = a.ctx.cloudFrameKey(a.product, a.slot, a.box, a.size);
  a.ctx.cloudFrames.set(key, { url: 'blob:cached', box: a.box, size: a.size });
  a.ctx.cloudNeedsReload = () => false;
  a.ctx.loadSatelliteClouds(true);
  assert.equal(nitide(a).length, 2);
  assert.equal(a.ctx.cloudToken, 2);
  await vecchia.arriva();
  assert.equal(a.pubblicazioni.length, 0, 'la vecchia richiesta viene ripubblicata');
  assert.ok(a.revocati.includes(vecchia.locale), 'il file della richiesta superata non viene liberato');
  await nitide(a)[1].arriva();
  assert.equal(a.pubblicazioni.length, 1);
});

provaAsync('un istante che il servizio non ha fa arretrare di un passo, sempre con l\'istante', async () => {
  const a = ambienteSatellite();
  a.ctx.loadSatelliteClouds(false);
  await nitide(a)[0].fallisce();
  assert.equal(nitide(a).length, 2);
  assert.match(nitide(a)[1].url, /\/122000\?/);
  await nitide(a)[1].arriva();
  assert.equal(a.pubblicazioni.length, 1);
});

provaAsync('la cache riusa solo lo stesso prodotto, istante, riquadro e risoluzione', async () => {
  const a = ambienteSatellite();
  a.ctx.loadSatelliteClouds(false);
  const vecchia = nitide(a)[0];
  const key = a.ctx.cloudFrameKey(a.product, a.slot, a.box, a.size);
  a.ctx.cloudFrames.set(key, { url: 'blob:cached', box: a.box, size: a.size });
  a.ctx.loadSatelliteClouds(false);
  assert.equal(nitide(a).length, 1, 'la cache richiede di nuovo la stessa immagine');
  assert.equal(a.aggiornamenti[0].url, 'blob:cached');
  await vecchia.arriva();
  assert.equal(a.pubblicazioni.length, 0, 'la risposta vecchia sovrascrive la cache');
  a.ctx.cloudPublishedKey = key;
  a.slot.value += 1000;
  a.ctx.loadSatelliteClouds(false);
  assert.equal(nitide(a).length, 2, 'un nuovo istante riusa il vecchio fotogramma');
  a.product.layer = 'mtg-ir';
  a.ctx.loadSatelliteClouds(false);
  assert.equal(nitide(a).length, 3, 'un altro canale riusa il vecchio fotogramma');
  a.box.west -= 1;
  a.ctx.loadSatelliteClouds(false);
  assert.equal(nitide(a).length, 4, 'un altro riquadro riusa il vecchio fotogramma');
  a.size.width *= 2;
  a.ctx.loadSatelliteClouds(false);
  assert.equal(a.richieste.filter(r => /w=3600$/.test(r.url)).length, 1, 'un altro zoom riusa la vecchia risoluzione');
});

prova('le etichette satellite riportano l\'istante del fotogramma pubblicato', () => {
  const vm = require('node:vm');
  const label = { textContent: '' };
  const ctx = {
    document: { getElementById: () => label },
    formatDateTime: date => date.toISOString()
  };
  vm.createContext(ctx);
  vm.runInContext(implementazione('syncTimelineToSatellite'), ctx);
  const date = new Date('2026-10-10T06:10:00Z');
  ctx.syncTimelineToSatellite({ latest: false, date });
  assert.equal(label.textContent, date.toISOString());
});

prova('la pagina usa solo script pubblicati e non carica comandi con dati fittizi', () => {
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
  const workflow = fs.readFileSync(path.join(root, '.github/workflows/update_meteo.yml'), 'utf8');
  for (const script of scripts) {
    const src = script[1].match(/\bsrc="([^"]+)"/);
    if (!src) continue;
    assert.equal(script[2].trim(), '', 'codice ignorato dentro uno script con src');
    if (/^https?:\/\//.test(src[1])) continue;
    assert.ok(workflow.includes(src[1]), src[1] + ' assente dalla pubblicazione');
  }
  assert.doesNotMatch(html, /src="scientific-ui\.js"/,
    'la pagina carica una seconda timeline scollegata e tooltip casuali');
});

Promise.all(asincrone).then(() => {
  console.log(ok ? 'ESITO: SUPERATO' : 'ESITO: DA RIVEDERE');
  process.exit(ok ? 0 : 1);
});
