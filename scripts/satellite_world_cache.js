// ============================================================================
// WORLD CACHE PER SATELLITE - Risolve il problema del dezoom
// ============================================================================
// Il problema: quando si fa dezoom, si vede solo la parte che era zommata
// perché il sistema carica una nuova immagine grande ogni volta.
//
// La soluzione: mantenere una cache di immagini a diversi zoom levels.
// Quando si dezooma, usare l'immagine cached (anche se meno dettagliata)
// invece di aspettare il download di una nuova immagine.
// ============================================================================

(function() {
  "use strict";

  class SatelliteWorldCache {
    constructor() {
      // Cache strutturata per zoom level
      // Struttura: Map<zoomLevel, Array<{image, box, size, timestamp, quality}>>
      this.cacheByZoom = new Map();
      
      // Configurazione
      this.maxZoomLevels = 8; // Mantieni fino a 8 zoom levels diversi
      this.maxImagesPerLevel = 3; // Max 3 immagini per zoom level
      
      // Statistiche
      this.stats = {
        hits: 0,
        misses: 0,
        prefetches: 0
      };
      
      console.log("[WorldCache] Inizializzato");
    }
    
    // Salva un'immagine nella cache per un dato zoom level
    cacheImage(zoom, image, box, size, timestamp) {
      const zoomLevel = Math.round(zoom);
      
      if (!this.cacheByZoom.has(zoomLevel)) {
        this.cacheByZoom.set(zoomLevel, []);
      }
      
      const levelCache = this.cacheByZoom.get(zoomLevel);
      
      // Controlla se esiste già un'immagine simile
      const existingIndex = levelCache.findIndex(img => 
        Math.abs(img.box.west - box.west) < 0.1 &&
        Math.abs(img.box.south - box.south) < 0.1 &&
        Math.abs(img.box.east - box.east) < 0.1 &&
        Math.abs(img.box.north - box.north) < 0.1
      );
      
      if (existingIndex >= 0) {
        // Aggiorna timestamp
        levelCache[existingIndex].timestamp = timestamp;
        levelCache[existingIndex].lastAccess = Date.now();
        return;
      }
      
      // Aggiungi nuova immagine
      levelCache.push({
        image: image,
        box: box,
        size: size,
        timestamp: timestamp,
        lastAccess: Date.now(),
        quality: 1.0
      });
      
      // Rimuovi immagini vecchie se necessario
      if (levelCache.length > this.maxImagesPerLevel) {
        // Ordina per ultimo accesso (LRU)
        levelCache.sort((a, b) => b.lastAccess - a.lastAccess);
        levelCache.length = this.maxImagesPerLevel;
      }
      
      // Rimuovi zoom levels vecchi se necessario
      if (this.cacheByZoom.size > this.maxZoomLevels) {
        // Trova il zoom level meno recentemente usato
        let oldestZoom = null;
        let oldestTime = Infinity;
        
        for (const [zoom, images] of this.cacheByZoom.entries()) {
          const latestAccess = Math.max(...images.map(img => img.lastAccess));
          if (latestAccess < oldestTime) {
            oldestTime = latestAccess;
            oldestZoom = zoom;
          }
        }
        
        if (oldestZoom !== null && oldestZoom !== zoomLevel) {
          this.cacheByZoom.delete(oldestZoom);
        }
      }
      
      console.log(`[WorldCache] Cached image at zoom ${zoomLevel} (total levels: ${this.cacheByZoom.size})`);
    }
    
    // Trova la migliore immagine cached per un dato zoom e area
    findBestImage(zoom, targetBox) {
      const zoomLevel = Math.round(zoom);
      
      // Cerca prima allo zoom level esatto
      if (this.cacheByZoom.has(zoomLevel)) {
        const candidates = this.cacheByZoom.get(zoomLevel);
        const match = this.findBestMatch(candidates, targetBox);
        if (match) {
          this.stats.hits++;
          match.lastAccess = Date.now();
          return { image: match.image, box: match.box, size: match.size, quality: 1.0 };
        }
      }
      
      // Se non trovato, cerca a zoom levels vicini
      const searchRadius = 3; // Cerca fino a 3 zoom levels di distanza
      let bestMatch = null;
      let bestQuality = 0;
      
      for (let delta = -searchRadius; delta <= searchRadius; delta++) {
        if (delta === 0) continue; // Già controllato
        
        const searchZoom = zoomLevel + delta;
        if (!this.cacheByZoom.has(searchZoom)) continue;
        
        const candidates = this.cacheByZoom.get(searchZoom);
        const match = this.findBestMatch(candidates, targetBox);
        
        if (match) {
          // Qualità basata sulla vicinanza dello zoom level
          const quality = 1.0 - Math.abs(delta) * 0.2;
          
          if (quality > bestQuality) {
            bestQuality = quality;
            bestMatch = { image: match.image, box: match.box, size: match.size, quality };
          }
        }
      }
      
      if (bestMatch) {
        this.stats.hits++;
        return bestMatch;
      }
      
      this.stats.misses++;
      return null;
    }
    
    // Trova il miglior match tra le candidate images
    findBestMatch(candidates, targetBox) {
      if (!candidates || candidates.length === 0) return null;
      
      let bestMatch = null;
      let bestScore = 0;
      
      for (const candidate of candidates) {
        const score = this.calculateOverlapScore(candidate.box, targetBox);
        if (score > bestScore) {
          bestScore = score;
          bestMatch = candidate;
        }
      }
      
      // Richiedi almeno 30% di overlap
      return bestScore >= 0.3 ? bestMatch : null;
    }
    
    // Calcola quanto due box si sovrappongono (0-1)
    calculateOverlapScore(box1, box2) {
      const overlapWest = Math.max(box1.west, box2.west);
      const overlapEast = Math.min(box1.east, box2.east);
      const overlapSouth = Math.max(box1.south, box2.south);
      const overlapNorth = Math.min(box1.north, box2.north);
      
      if (overlapWest >= overlapEast || overlapSouth >= overlapNorth) {
        return 0; // Nessun overlap
      }
      
      const overlapArea = (overlapEast - overlapWest) * (overlapNorth - overlapSouth);
      const targetArea = (box2.east - box2.west) * (box2.north - box2.south);
      
      return overlapArea / targetArea;
    }
    
    // Precarica immagini per zoom levels vicini
    prefetchZoomLevels(currentZoom, currentBox, loadFunction) {
      const zoomLevel = Math.round(currentZoom);
      
      // Precarica zoom levels adiacenti
      const prefetchZooms = [zoomLevel - 2, zoomLevel - 1, zoomLevel + 1, zoomLevel + 2];
      
      for (const targetZoom of prefetchZooms) {
        if (targetZoom < 0 || targetZoom > 18) continue; // Limiti ragionevoli
        
        // Controlla se abbiamo già immagini per questo zoom
        if (this.cacheByZoom.has(targetZoom)) {
          const images = this.cacheByZoom.get(targetZoom);
          if (images.length >= this.maxImagesPerLevel) continue;
        }
        
        // Adatta il box per il nuovo zoom level
        const adjustedBox = this.adjustBoxForZoom(currentBox, currentZoom, targetZoom);
        
        // Avvia caricamento (se la funzione è fornita)
        if (loadFunction && typeof loadFunction === 'function') {
          console.log(`[WorldCache] Prefetching zoom ${targetZoom}`);
          this.stats.prefetches++;
          loadFunction(targetZoom, adjustedBox);
        }
      }
    }
    
    // Adatta un box per un diverso zoom level
    adjustBoxForZoom(box, currentZoom, targetZoom) {
      const zoomDiff = targetZoom - currentZoom;
      
      // Ad zoom più bassi, il box deve essere più grande
      // Ad zoom più alti, il box può essere più piccolo
      const scaleFactor = Math.pow(2, -zoomDiff);
      
      const centerLon = (box.west + box.east) / 2;
      const centerLat = (box.south + box.north) / 2;
      const halfWidth = (box.east - box.west) / 2 * scaleFactor;
      const halfHeight = (box.north - box.south) / 2 * scaleFactor;
      
      return {
        west: centerLon - halfWidth,
        east: centerLon + halfWidth,
        south: centerLat - halfHeight,
        north: centerLat + halfHeight
      };
    }
    
    // Statistiche
    getStats() {
      return {
        ...this.stats,
        cachedZoomLevels: this.cacheByZoom.size,
        totalImages: Array.from(this.cacheByZoom.values()).reduce((sum, arr) => sum + arr.length, 0),
        hitRate: this.stats.hits / (this.stats.hits + this.stats.misses) || 0
      };
    }
    
    // Pulizia periodica delle immagini troppo vecchie
    cleanup(maxAgeMs = 15 * 60 * 1000) { // 15 minuti
      const now = Date.now();
      
      for (const [zoom, images] of this.cacheByZoom.entries()) {
        const filtered = images.filter(img => now - img.lastAccess < maxAgeMs);
        
        if (filtered.length === 0) {
          this.cacheByZoom.delete(zoom);
        } else if (filtered.length < images.length) {
          this.cacheByZoom.set(zoom, filtered);
        }
      }
    }
  }
  
  // ========================================================================
  // LEGENDA SCIENTIFICA PER RADAR E FULMINI
  // ========================================================================
  
  class ScientificLegend {
    constructor() {
      this.container = null;
      this.createContainer();
    }
    
    createContainer() {
      // Crea container per la legenda
      this.container = document.createElement('div');
      this.container.id = 'scientific-legend';
      this.container.style.cssText = `
        position: fixed;
        right: 20px;
        top: 100px;
        background: rgba(20, 30, 40, 0.95);
        border: 1px solid rgba(100, 150, 200, 0.3);
        border-radius: 8px;
        padding: 12px;
        color: #e0e8f0;
        font-family: 'SF Mono', Monaco, monospace;
        font-size: 11px;
        max-width: 200px;
        z-index: 1000;
        display: none;
        backdrop-filter: blur(10px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
      `;
      
      document.body.appendChild(this.container);
    }
    
    show(type) {
      if (type === 'radar') {
        this.showRadarLegend();
      } else if (type === 'lightning') {
        this.showLightningLegend();
      }
      
      this.container.style.display = 'block';
    }
    
    hide() {
      this.container.style.display = 'none';
    }
    
    showRadarLegend() {
      // Legenda scientifica per radar (riflettività dBZ)
      const ranges = [
        { min: 5, max: 10, color: '#64e6e6', label: 'Pioviggine' },
        { min: 10, max: 20, color: '#00aaff', label: 'Pioggia leggera' },
        { min: 20, max: 30, color: '#0050dd', label: 'Pioggia moderata' },
        { min: 30, max: 40, color: '#00d000', label: 'Rovescio' },
        { min: 40, max: 50, color: '#ffaa00', label: 'Temporale' },
        { min: 50, max: 60, color: '#ff0000', label: 'Grandine' },
        { min: 60, max: 70, color: '#cc00ff', label: 'Grandine severa' }
      ];
      
      let html = `
        <div style="font-weight: bold; margin-bottom: 8px; color: #88ccff;">
          Radar Precipitazioni
        </div>
        <div style="margin-bottom: 4px; color: #a0b0c0;">Riflettività (dBZ)</div>
      `;
      
      for (const range of ranges) {
        html += `
          <div style="display: flex; align-items: center; margin: 4px 0;">
            <div style="width: 20px; height: 12px; background: ${range.color}; border-radius: 2px; margin-right: 8px;"></div>
            <div>${range.min}-${range.max} dBZ</div>
            <div style="margin-left: auto; color: #80a0b0; font-size: 10px;">${range.label}</div>
          </div>
        `;
      }
      
      html += `
        <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(100, 150, 200, 0.2); font-size: 10px; color: #80a0b0;">
          RainViewer HD · Aggiornato ogni 5 min
        </div>
      `;
      
      this.container.innerHTML = html;
    }
    
    showLightningLegend() {
      // Legenda scientifica per fulmini
      let html = `
        <div style="font-weight: bold; margin-bottom: 8px; color: #ffdd88;">
          Scariche Elettriche
        </div>
        <div style="margin-bottom: 8px; color: #a0b0c0;">Età della scarica:</div>
        
        <div style="display: flex; align-items: center; margin: 4px 0;">
          <div style="width: 12px; height: 12px; background: #ffff00; border-radius: 50%; margin-right: 8px;"></div>
          <div>0-2 min</div>
          <div style="margin-left: auto; color: #80a0b0; font-size: 10px;">Recentissima</div>
        </div>
        
        <div style="display: flex; align-items: center; margin: 4px 0;">
          <div style="width: 12px; height: 12px; background: #ffaa00; border-radius: 50%; margin-right: 8px;"></div>
          <div>2-10 min</div>
          <div style="margin-left: auto; color: #80a0b0; font-size: 10px;">Recente</div>
        </div>
        
        <div style="display: flex; align-items: center; margin: 4px 0;">
          <div style="width: 12px; height: 12px; background: #ff5500; border-radius: 50%; margin-right: 8px;"></div>
          <div>10-20 min</div>
          <div style="margin-left: auto; color: #80a0b0; font-size: 10px;">Vecchia</div>
        </div>
        
        <div style="display: flex; align-items: center; margin: 4px 0;">
          <div style="width: 12px; height: 12px; background: #cc0000; border-radius: 50%; margin-right: 8px;"></div>
          <div>20-30 min</div>
          <div style="margin-left: auto; color: #80a0b0; font-size: 10px;">In dissolvenza</div>
        </div>
        
        <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(100, 150, 200, 0.2);">
          <div style="font-weight: bold; margin-bottom: 4px; color: #ffdd88;">Dimensione:</div>
          <div style="font-size: 10px; color: #80a0b0;">
            Raggio proporzionale alla corrente (kA)
          </div>
        </div>
        
        <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(100, 150, 200, 0.2); font-size: 10px; color: #80a0b0;">
          Blitzortung · Live · Traccia 150s
        </div>
      `;
      
      this.container.innerHTML = html;
    }
  }
  
  // ========================================================================
  // ESPORTA NEL GLOBALE
  // ========================================================================
  
  window.SatelliteWorldCache = SatelliteWorldCache;
  window.ScientificLegend = ScientificLegend;
  
  // Inizializza automaticamente
  window.worldCache = new SatelliteWorldCache();
  window.scientificLegend = new ScientificLegend();
  
  console.log("[WorldCache/Legend] Moduli caricati e inizializzati");
})();
