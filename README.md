# Sicilia Meteo · ICON-2I Scientific Platform

Piattaforma meteorologica professionale focalizzata sul modello **ICON-2I** (Icosahedral Nonhydrostatic, 2km resolution).

## 🎯 Caratteristiche Principali

### Interfaccia Scientifica Professionale
- **Sidebar Windy-style**: Selezione rapida parametri con icone minimaliste
- **Timeline avanzata**: Navigazione temporale fluida con animazione
- **Legende dinamiche**: Palette colori scientificamente validate per ogni parametro
- **Tooltip arricchiti**: Informazioni dettagliate al passaggio del mouse

### Parametri Meteorologici ICON-2I

#### Parametri Base
| Parametro | Unità | Descrizione |
|-----------|-------|-------------|
| **Temperatura** | °C | Temperatura a 2m dal suolo |
| **Vento** | km/h | Velocità e direzione vento a 10m |
| **Precipitazioni** | mm | Precipitazioni totali (pioggia/neve) |
| **Nuvolosità** | % | Copertura nuvolosa totale |
| **Pressione** | hPa | Pressione a livello del mare (MSL) |
| **Umidità** | % | Umidità relativa a 2m |

#### Parametri Avanzati (Nuovi)
| Parametro | Unità | Descrizione Scientifica |
|-----------|-------|------------------------|
| **CAPE** | J/kg | Convective Available Potential Energy - Energia potenziale convettiva disponibile |
| **CIN** | J/kg | Convective Inhibition - Energia di inibizione convettiva |
| **Lifted Index** | °C | Indice di stabilità atmosferica (valori negativi = instabilità) |
| **Bulk Shear 0-6km** | m/s | Wind shear verticale per identificazione supercelle |
| **Elicità 0-3km** | m²/s² | Storm Relative Helicity - Potenzialità tornadica |
| **Visibilità** | km | Visibilità orizzontale (nebbia/foschia) |

### Palette Colori Scientifiche

Le palette colori sono state progettate seguendo standard meteorologici internazionali:

#### Temperatura (-30°C → +40°C)
- Blu scuro → Blu → Verde → Giallo → Arancione → Rosso
- Transizione a 0°C (verde) per identificazione punto di congelamento

#### Vento (0 → 150 km/h)
- Bianco (calma) → Azzurro → Blu → Viola scuro
- Scala logaritmica per evidenziare venti forti

#### Precipitazioni (0 → 50 mm/h)
- Verde chiaro (pioviggine) → Verde scuro → Rosso (rovesci) → Viola (nubifragi)

#### CAPE (0 → 4000 J/kg)
- Bianco (stabile) → Giallo → Arancione → Rosso (molto instabile)
- Soglie: <1000 debole, 1000-2500 moderato, >2500 forte

### Classificazione e Tracking dei Fronti (Nuovo in v2.1.0)

Il sistema ora include classificazione completa e tracking temporale dei fronti:

#### Classificazione Tipo Fronte
- **Freddo**: Avvezione termica ≤ -1.5 K/(3h), trough di pressione
- **Caldo**: Avvezione termica ≥ 1.0 K/(3h)
- **Occluso**: Struttura verticale complessa (cold-type o warm-type)
- **Stazionario**: Velocità < 5 km/h o avvezione debole

#### Tracking Temporale
- Identificazione dello stesso fronte attraverso time steps consecutivi
- Calcolo velocità di propagazione (km/h)
- Rilevamento automatico di frontogenesi e frontolisi
- Nowcasting della posizione futura (6h ahead)

Vedi `scripts/example_usage.py` per esempi completi.

### Strumenti Scientifici

#### Meteogrammi Avanzati
- Grafici interattivi con zoom e tooltip
- Visualizzazione multi-parametro sincronizzata
- Confronto osservazioni vs modello

#### Sezioni Verticali (Pianificato)
- Cross-sections atmosferiche
- Profili verticali temperatura/umidità/vento
- Identificazione fronti e inversioni termiche

#### Diagramma Skew-T/log-P (Pianificato)
- Analisi termodinamica completa
- Calcolo CAPE/CIN grafico
- LFC (Level of Free Convection) e EL (Equilibrium Level)
- Wind barbs a vari livelli

#### Hodograph (Pianificato)
- Grafico polare vento 0-10km
- Calcolo Bulk Shear e SRH
- Classificazione tipologia temporale

### Architettura Tecnica

#### Frontend
- **MapLibre GL 5.24.0**: Rendering mappe vettoriali ad alte prestazioni
- **Web Workers**: Elaborazione raster senza bloccare l'interfaccia
- **Canvas API**: Rendering particelle vento e vettori
- **Sistema di caching**: FrameCache con budget di memoria controllato

#### Backend (Python)
- **Pipeline elaborazione**: `scripts/` e `meteo_analysis/`
- **Rilevamento fronti**: Algoritmi avanzati di analisi sinottica
- **Downscaling locale**: Correzioni fisiche basate su osservazioni
- **Nowcasting**: Previsioni a brevissimo termine per nuvole

#### Ottimizzazioni ICON-2I
- **Risoluzione 2km**: Sfruttata per dettagli orografici fini
- **Pre-warming frame**: Animazioni fluide con precaricamento
- **Tile caching**: Cache aggressiva per zoom alti
- **Lazy loading**: Caricamento dati solo per area visibile

## 🚀 Utilizzo

### Navigazione Mappa
- **Zoom**: Rotella mouse o pinch su mobile
- **Pan**: Trascinamento con mouse/dito
- **Selezione punto**: Click sulla mappa per dettagli località

### Sidebar Parametri
1. Clicca sull'icona del parametro desiderato nella sidebar sinistra
2. La mappa mostra immediatamente il layer selezionato
3. La legenda in basso a destra si aggiorna automaticamente

### Timeline Temporale
1. Usa i controlli play/pause per animare le previsioni
2. Trascina lo scrubber per navigare nel tempo
3. Clicca sulla track per saltare a un orario specifico

### Tooltip Dettagliati
- Passa il mouse sulla mappa per vedere i valori dei parametri
- Informazioni multiple visualizzate contemporaneamente
- Coordinate geografiche ed elevazione mostrate

## 📊 Focus ICON-2I

Questo progetto è ottimizzato esclusivamente per il modello **ICON-2I**:
- **Risoluzione spaziale**: 2 km (ideale per dettagli locali)
- **Copertura**: Europa con focus su Italia/Sicilia
- **Frequenza aggiornamento**: Ogni 6 ore (00, 06, 12, 18 UTC)
- **Orizzonte previsionale**: 72 ore

### Vantaggi ICON-2I
- Alta risoluzione per fenomeni locali (brezze, effetti orografici)
- Buona rappresentazione di fronti e sistemi convettivi
- Aggiornamenti frequenti per nowcasting

## 🔧 Sviluppi Futuri

### Priorità Alta
- [ ] Implementazione Skew-T/log-P nei meteogrammi
- [ ] Sezioni verticali (cross-sections) interattive
- [ ] Hodograph per analisi vento in quota
- [ ] Verifica modello vs osservazioni (MAE, RMSE, Bias)

### Priorità Media
- [ ] Layer specifici: riflettività simulata, tipo precipitazione
- [ ] Service Workers per caching offline
- [ ] Ottimizzazioni WebGL per rendering complesso
- [ ] Integrazione dati stazioni meteo in tempo reale

### Priorità Bassa
- [ ] Modalità scura/chiara personalizzabile
- [ ] Esportazione dati (CSV, JSON)
- [ ] API pubblica per accesso programmatico
- [ ] Widget embeddable per siti esterni

## 📝 Licenza

Progetto open source per uso scientifico e didattico.

## 🤝 Contributi

Contributi e suggerimenti sono benvenuti. Per segnalare bug o proporre nuove funzionalità, aprire una issue su GitHub.

---

**Ultimo aggiornamento**: 2026-10-09  
**Modello**: ICON-2I (2km)  
**Sviluppato per**: Analisi meteorologica professionale
