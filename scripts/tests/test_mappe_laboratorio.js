'use strict';
// Le scelte del laboratorio delle mappe (08/11/2026): carta scura, vento a
// scie colorate, neve distinta dalla pioggia, temporali che pulsano con i
// lampi, valori sulle citta', sonda sotto il puntatore, isobare con A e B
// accese, dissolvenza fra le ore.
//
// Queste prove sorvegliano le regole che rendono onesti gli effetti: la neve
// e' decisa dal bulbo umido, un lampo compare solo dove il modello ha il
// segnale convettivo, la dissolvenza non inventa ore intermedie.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.resolve(__dirname, '../../index.html'), 'utf8');

function implementazione(nome) {
  const inizio = html.indexOf('      function ' + nome + '(');
  assert.ok(inizio >= 0, 'manca ' + nome);
  return html.slice(inizio, html.indexOf('\n      }\n', inizio) + 8);
}
function tabella(nome) {
  const trovata = html.match(new RegExp('const ' + nome + ' = \\[[\\s\\S]*?\\n      \\];'));
  assert.ok(trovata, 'manca la tabella ' + nome);
  return trovata[0];
}
function costante(nome) {
  const trovata = html.match(new RegExp('const ' + nome + ' = [^;]+;'));
  assert.ok(trovata, 'manca ' + nome);
  return trovata[0];
}

let ok = true;
function prova(nome, fn) {
  try { fn(); console.log('PASS ' + nome); }
  catch (errore) { ok = false; console.log('FALLITO ' + nome + ': ' + errore.message); }
}

prova('la carta e\' scura ma non nera', () => {
  const luce = function (hex) {
    const n = parseInt(hex.slice(1), 16);
    return 0.2126 * (n >> 16) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255);
  };
  const terra = html.match(/const MAP_LAND = "(#[0-9a-f]{6})";/)[1];
  const mare = html.match(/const MAP_SEA = "(#[0-9a-f]{6})";/)[1];
  assert.ok(luce(terra) < 60 && luce(mare) < 60, 'la carta non e\' scura');
  assert.ok(luce(terra) > 8 && luce(mare) > 8, 'la carta e\' nera');
  assert.ok(luce(terra) > luce(mare) + 6, 'terra e mare non si distinguono');
  // Sulla carta scura i nomi sono chiari con alone scuro, la costa ha il
  // filo scuro sotto per leggersi sopra i campi accesi.
  assert.match(implementazione('drawPlaceNames'), /const onPhoto = !synopticChart;/,
    'i toponimi restano scuri sulla carta scura');
  assert.match(html, /id: "base-coast-casing"/, 'la costa non ha il filo scuro sotto');
});

prova('la neve si colora dal bulbo umido, con una fascia mista', () => {
  const codice = [
    'const clamp = (v, a, b) => Math.max(a, Math.min(b, v));',
    tabella('RAIN_STOPS'), tabella('SNOW_STOPS'),
    costante('SNOW_WETBULB_SNOW'), costante('SNOW_WETBULB_RAIN'),
    implementazione('getGrid'), implementazione('sampleNearest'),
    implementazione('sampleBilinear'), implementazione('sampleCoarseBilinear'),
    implementazione('colorFor'), implementazione('fillRasterPixels'),
    'this.RAIN_STOPS = RAIN_STOPS; this.SNOW_STOPS = SNOW_STOPS;',
    'this.SNOW_WETBULB_SNOW = SNOW_WETBULB_SNOW; this.SNOW_WETBULB_RAIN = SNOW_WETBULB_RAIN;',
    'this.colorFor = colorFor; this.fillRasterPixels = fillRasterPixels;'
  ].join('\n');
  const ctx = { Math, Number, Float32Array, Uint8ClampedArray, Array, Object };
  vm.createContext(ctx);
  vm.runInContext(codice, ctx);
  // Tre colonne: bulbo -2 (neve), 1 (misto), 4 (pioggia). Piove 5 mm ovunque.
  const params = {
    width: 3, height: 1, leftLongitude: 0, rightLongitude: 2,
    topMercator: 0, bottomMercator: 0,
    fieldMeta: { lo1: 0, la1: 0, dx: 1, dy: 1, nx: 3, ny: 1 },
    samplerKind: 'nearest', isWindField: false,
    fieldGrid: new Float32Array([5, 5, 5]),
    info: { stops: ctx.RAIN_STOPS, discrete: true },
    activeLayer: 'rain',
    snowGrid: new Float32Array([-2, 1, 4]),
    snowInfo: { stops: ctx.SNOW_STOPS, discrete: true, snowBelow: ctx.SNOW_WETBULB_SNOW, rainAbove: ctx.SNOW_WETBULB_RAIN }
  };
  const px = ctx.fillRasterPixels(params).pixels;
  const neve = Array.from(ctx.colorFor(5, params.snowInfo)), pioggia = Array.from(ctx.colorFor(5, params.info));
  assert.deepEqual(Array.from(px.slice(0, 3)), neve.slice(0, 3).map(Math.round), 'col bulbo sotto zero non e\' neve');
  assert.deepEqual(Array.from(px.slice(8, 11)), pioggia.slice(0, 3).map(Math.round), 'col bulbo a 4 gradi non e\' pioggia');
  for (let c = 0; c < 3; c += 1) {
    const basso = Math.min(neve[c], pioggia[c]) - 1, alto = Math.max(neve[c], pioggia[c]) + 1;
    assert.ok(px[4 + c] >= basso && px[4 + c] <= alto, 'la fascia mista non sta fra neve e pioggia');
  }
  // Senza bulbo umido (altri campi o dati mancanti) il raster resta quello di prima.
  const senza = ctx.fillRasterPixels(Object.assign({}, params, { snowGrid: null })).pixels;
  assert.deepEqual(Array.from(senza.slice(0, 3)), pioggia.slice(0, 3).map(Math.round));
});

prova('i lampi solo dove il modello ha il segnale convettivo', () => {
  const griglia = implementazione('grigliaEffetti');
  assert.match(html, /const EFFETTI_LAMPO_INDICE = (\d+);/);
  assert.ok(Number(html.match(/const EFFETTI_LAMPO_INDICE = (\d+);/)[1]) >= 40,
    'la soglia del lampo e\' troppo bassa');
  assert.match(griglia, /temporale: Number\.isFinite\(c\) && c >= EFFETTI_LAMPO_INDICE/,
    'un nucleo diventa temporale senza l\'indice convettivo');
  assert.match(griglia, /getGrid\(data\.convection_prob\)/, 'il lampo non legge l\'indice del modello');
  const ciclo = implementazione('cicloEffetti');
  assert.match(ciclo, /griglia\.nuclei\.filter\(function \(nucleo\) \{ return nucleo\.temporale; \}\)/,
    'i lampi possono cadere in nuclei senza segnale');
  // Neve dal bulbo umido, con la stessa soglia del raster.
  assert.match(griglia, /getGrid\(data\.wetbulb\)/, 'i fiocchi non seguono il bulbo umido');
  assert.match(griglia, /\(SNOW_WETBULB_SNOW \+ SNOW_WETBULB_RAIN\) \/ 2/, 'fiocchi e raster usano soglie diverse');
  const attivi = implementazione('effettiAttivi');
  assert.match(attivi, /activeLayer === "rain"/, 'gli effetti escono dal campo della pioggia');
  assert.match(attivi, /!prefersReducedMotion/, 'gli effetti ignorano le animazioni ridotte');
  assert.match(attivi, /!synopticChart/, 'gli effetti finiscono sulla carta sinottica');
  assert.match(implementazione('drawVectors'), /avviaEffettiPioggia\(\);/, 'gli effetti non partono mai');
});

prova('i valori sulle citta\' sono quelli della scheda del punto', () => {
  const bollino = implementazione('valoreBollino');
  assert.match(bollino, /fieldValue\(activeLayer, punto\.gx, punto\.gy\)/,
    'il bollino non legge il valore come la scheda del punto');
  assert.match(bollino, /info\.categorical\) return null/, 'il bollino compare sulle classi');
  assert.match(bollino, /activeLayer === "rain" && valore < 0\.1\) return null/, 'il bollino mostra la pioggia assente');
  assert.match(implementazione('drawPlaceNames'), /valoreBollino\(place\.lon, place\.lat\)/,
    'i nomi delle citta\' non portano il valore');
  assert.match(html, /data-toggle="cityvalues"/, 'manca l\'interruttore dei valori sulle citta\'');
  assert.match(html, /let showIsobars = true;/, 'le isobare con A e B non sono accese da subito');
  const sonda = implementazione('collegaSonda');
  assert.match(sonda, /e\.pointerType !== "mouse"/, 'la sonda segue anche il dito che trascina la mappa');
});

prova('la dissolvenza passa fra due ore vere e rispetta le animazioni ridotte', () => {
  const prepara = implementazione('preparaDissolvenza');
  assert.match(prepara, /prefersReducedMotion/, 'la dissolvenza ignora le animazioni ridotte');
  assert.match(prepara, /prima\.chiave !== chiaveRaster\(\) \|\| prima\.indice === currentIndex/,
    'la dissolvenza parte anche cambiando campo o restando sulla stessa ora');
  const pubblica = implementazione('publishWeatherRaster');
  assert.match(pubblica, /preparaDissolvenza\(\);[\s\S]*?updateImage\(\{ url: url, coordinates: coordinates \}\);[\s\S]*?ricordaRaster\(url, coordinates\);/,
    'la dissolvenza non prepara l\'ora vecchia prima di caricare la nuova');
  assert.match(implementazione('chiudiDissolvenza'), /"weather-prev-layer", "visibility", "none"/,
    'l\'ora vecchia resta accesa sotto la nuova');
});

console.log(ok ? 'ESITO: SUPERATO' : 'ESITO: DA RIVEDERE');
process.exitCode = ok ? 0 : 1;
