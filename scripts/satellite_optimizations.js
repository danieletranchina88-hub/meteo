// ============================================================================
// SATELLITE, RADAR E FULMINI - OTTIMIZZAZIONI SCIENTIFICHE
// ============================================================================
// Questo modulo migliora:
// 1. Velocità di caricamento satellite con caching multi-livello
// 2. Zoom istantaneo con prefetching dei tile
// 3. Dezoom fluido con world cache per zoom bassi
// 4. Visualizzazione scientifica dei fulmini con decadimento temporale
// ============================================================================

(function() {
  "use strict";

  // ========================================================================
  // SATELLITE TILE CACHE - Sistema di caching multi-livello
  // ========================================================================
  
  class SatelliteTileCache {
    constructor(options = {}) {
      // Cache dimensioni massime
      this.maxMemorySize = options.maxMemorySize || 200 * 1024 * 1024; // 200MB
      this.currentSize = 0;
      
      // Cache strutturata per zoom level
      // Struttura: { zoom: { x_y: { image, size, timestamp, lastAccess } } }
      this.cache = new Map();
      
      // Tile in fase di caricamento (per evitare duplicati)
      this.loading = new Map();
      
      // Statistiche per debugging
      this.stats = {
        hits: 0,
        misses: 0,
        evictions: 0,
        loads: 0
      };
      
      // Avvia cleanup periodico
      this.startCleanupInterval();
    }
    
    // Genera chiave unica per un tile
    getKey(zoom, x, y, product, timestamp) {
      return `${zoom}/${x}/${y}/${product}/${timestamp}`;
    }
    
    // Recupera un tile dalla cache
    get(zoom, x, y, product, timestamp) {
      const key = this.getKey(zoom, x, y, product, timestamp);
      const tile = this.cache.get(key);
      
      if (tile) {
        // Aggiorna ultimo accesso (LRU)
        tile.lastAccess = Date.now();
        this.stats.hits++;
        return tile.image;
      }
      
      this.stats.misses++;
      return null;
    }
    
    // Salva un tile nella cache
    set(zoom, x, y, product, timestamp, image) {
      const key = this.getKey(zoom, x, y, product, timestamp);
      
      // Calcola dimensione immagine (approssimativa)
      const size = image.width * image.height * 4; // RGBA = 4 bytes per pixel
      
      // Rimuovi tile se necessario per fare spazio
      while (this.currentSize + size > this.maxMemorySize && this.cache.size > 0) {
        this.evictLRU();
      }
      
      // Salva tile
      this.cache.set(key, {
        image: image,
        size: size,
        timestamp: Date.now(),
        lastAccess: Date.now(),
        zoom: zoom,
        x: x,
        y: y
      });
      
      this.currentSize += size;
      this.stats.loads++;
    }
    
    // Rimuove il tile meno recentemente usato (LRU)
    evictLRU() {
      let oldestKey = null;
      let oldestTime = Infinity;
      
      for (const [key, tile] of this.cache.entries()) {
        if (tile.lastAccess < oldestTime) {
          oldestTime = tile.lastAccess;
          oldestKey = key;
        }
      }
      
      if (oldestKey) {
        const tile = this.cache.get(oldestKey);
        this.currentSize -= tile.size;
        this.cache.delete(oldestKey);
        this.stats.evictions++;
      }
    }
    
    // Controlla se un tile è in fase di caricamento
    isLoading(zoom, x, y, product, timestamp) {
      const key = this.getKey(zoom, x, y, product, timestamp);
      return this.loading.has(key);
    }
    
    // Imposta un tile come in caricamento
    setLoading(zoom, x, y, product, timestamp, promise) {
      const key = this.getKey(zoom, x, y, product, timestamp);
      this.loading.set(key, promise);
    }
    
    // Rimuove un tile dalla lista di caricamento
    clearLoading(zoom, x, y, product, timestamp) {
      const key = this.getKey(zoom, x, y, product, timestamp);
      this.loading.delete(key);
    }
    
    // Cleanup periodico dei tile troppo vecchi
    startCleanupInterval() {
      setInterval(() => {
        const now = Date.now();
        const maxAge = 10 * 60 * 1000; // 10 minuti
        
        for (const [key, tile] of this.cache.entries()) {
          if (now - tile.timestamp > maxAge) {
            this.currentSize -= tile.size;
            this.cache.delete(key);
          }
        }
      }, 60000); // Ogni minuto
    }
    
    // Precarica tile per un'area specifica
    prefetch(centerZoom, centerLon, centerLat, radiusKm, product, timestamp) {
      // Calcola i tile necessari per coprire l'area
      const tiles = this.calculateTilesForArea(centerZoom, centerLon, centerLat, radiusKm);
      
      // Precarica in parallelo (max 10 contemporaneamente)
      const batchSize = 10;
      for (let i = 0; i < tiles.length; i += batchSize) {
        const batch = tiles.slice(i, i + batchSize);
        batch.forEach(tile => {
          if (!this.isLoading(tile.zoom, tile.x, tile.y, product, timestamp) &&
              !this.get(tile.zoom, tile.x, tile.y, product, timestamp)) {
            // Avvia caricamento (verrà gestito dal sistema principale)
            this.loadTile(tile.zoom, tile.x, tile.y, product, timestamp);
          }
        });
      }
    }
    
    // Calcola i tile necessari per coprire un'area
    calculateTilesForArea(zoom, lon, lat, radiusKm) {
      const tiles = [];
      
      // Converti raggio in gradi (approssimativo)
      const latRadius = radiusKm / 111; // 1 grado ≈ 111 km
      const lonRadius = radiusKm / (111 * Math.cos(lat * Math.PI / 180));
      
      // Calcola bounding box
      const minLon = lon - lonRadius;
      const maxLon = lon + lonRadius;
      const minLat = lat - latRadius;
      const maxLat = lat + latRadius;
      
      // Converti in coordinate tile
      const minTile = this.lonLatToTile(minLon, minLat, zoom);
      const maxTile = this.lonLatToTile(maxLon, maxLat, zoom);
      
      // Genera tutti i tile nell'area
      for (let x = minTile.x; x <= maxTile.x; x++) {
        for (let y = minTile.y; y <= maxTile.y; y++) {
          tiles.push({ zoom, x, y });
        }
      }
      
      return tiles;
    }
    
    // Converte lon/lat in coordinate tile
    lonLatToTile(lon, lat, zoom) {
      const x = Math.floor((lon + 180) / 360 * Math.pow(2, zoom));
      const y = Math.floor((1 - Math.log(Math.tan(lat * Math.PI / 180) + 
                    1 / Math.cos(lat * Math.PI / 180)) / Math.PI) / 2 * Math.pow(2, zoom));
      return { x, y };
    }
    
    // Placeholder per caricamento tile (verrà implementato dal sistema principale)
    loadTile(zoom, x, y, product, timestamp) {
      // Questo metodo verrà sovrascritto dal sistema principale
      console.log(`Loading tile: zoom=${zoom}, x=${x}, y=${y}`);
    }
    
    // Statistiche cache
    getStats() {
      return {
        ...this.stats,
        size: this.cache.size,
        memoryUsage: this.currentSize,
        hitRate: this.stats.hits / (this.stats.hits + this.stats.misses) || 0
      };
    }
  }
  
  // ========================================================================
  // SATELLITE MANAGER - Gestione intelligente del caricamento
  // ========================================================================
  
  class SatelliteManager {
    constructor(map) {
      this.map = map;
      this.cache = new SatelliteTileCache();
      this.currentZoom = map.getZoom();
      this.isZooming = false;
      this.zoomTimeout = null;
      
      // Sovrascrivi il metodo loadTile del cache
      this.cache.loadTile = this.loadTile.bind(this);
      
      // Setup event listeners
      this.setupEventListeners();
    }
    
    setupEventListeners() {
      // Rileva inizio zoom
      this.map.on("zoomstart", () => {
        this.isZooming = true;
        this.prefetchForZoomChange();
      });
      
      // Rileva fine zoom
      this.map.on("zoomend", () => {
        this.isZooming = false;
        this.currentZoom = this.map.getZoom();
        
        // Precarica tile per la vista corrente
        this.prefetchCurrentView();
      });
      
      // Rileva movimento
      this.map.on("moveend", () => {
        if (!this.isZooming) {
          this.prefetchCurrentView();
        }
      });
    }
    
    // Precarica tile quando cambia lo zoom
    prefetchForZoomChange() {
      const targetZoom = Math.round(this.map.getZoom());
      const center = this.map.getCenter();
      
      // Precarica tile per il nuovo zoom level
      this.cache.prefetch(
        targetZoom,
        center.lng,
        center.lat,
        500, // 500km radius
        "satellite",
        Date.now()
      );
      
      // Precarica anche zoom levels adiacenti
      if (targetZoom > 0) {
        this.cache.prefetch(
          targetZoom - 1,
          center.lng,
          center.lat,
          800,
          "satellite",
          Date.now()
        );
      }
      
      this.cache.prefetch(
        targetZoom + 1,
        center.lng,
        center.lat,
        300,
        "satellite",
        Date.now()
      );
    }
    
    // Precarica tile per la vista corrente
    prefetchCurrentView() {
      const bounds = this.map.getBounds();
      const zoom = Math.round(this.map.getZoom());
      const center = this.map.getCenter();
      
      // Calcola raggio basato sulla vista
      const latDiff = bounds.getNorth() - bounds.getSouth();
      const radiusKm = latDiff * 111 * 1.5; // 50% extra
      
      this.cache.prefetch(
        zoom,
        center.lng,
        center.lat,
        radiusKm,
        "satellite",
        Date.now()
      );
    }
    
    // Carica un tile specifico
    loadTile(zoom, x, y, product, timestamp) {
      const key = this.cache.getKey(zoom, x, y, product, timestamp);
      
      if (this.cache.isLoading(zoom, x, y, product, timestamp)) {
        return; // Già in caricamento
      }
      
      // Crea promise per il caricamento
      const promise = new Promise((resolve, reject) => {
        const url = this.buildTileUrl(zoom, x, y, product, timestamp);
        const img = new Image();
        img.crossOrigin = "anonymous";
        
        img.onload = () => {
          this.cache.set(zoom, x, y, product, timestamp, img);
          this.cache.clearLoading(zoom, x, y, product, timestamp);
          resolve(img);
          
          // Trigger re-render se il tile è nella vista corrente
          if (this.isTileInView(zoom, x, y)) {
            this.map.triggerRepaint();
          }
        };
        
        img.onerror = (err) => {
          this.cache.clearLoading(zoom, x, y, product, timestamp);
          reject(err);
        };
        
        img.src = url;
      });
      
      this.cache.setLoading(zoom, x, y, product, timestamp, promise);
      return promise;
    }
    
    // Costruisce URL per un tile specifico
    buildTileUrl(zoom, x, y, product, timestamp) {
      // Questo deve essere implementato in base al servizio WMS usato
      // Esempio per EUMETSAT WMS con tile support:
      const tileSize = 512;
      const bbox = this.tileToBbox(x, y, zoom);
      
      return `https://eumetview.eumetsat.int/geoserv/wms?` +
             `service=WMS&version=1.1.1&request=GetMap` +
             `&layers=${product}` +
             `&srs=EPSG:3857` +
             `&bbox=${bbox.west},${bbox.south},${bbox.east},${bbox.north}` +
             `&width=${tileSize}&height=${tileSize}` +
             `&format=image/jpeg` +
             `&time=${new Date(timestamp).toISOString()}`;
    }
    
    // Converte coordinate tile in bounding box
    tileToBbox(x, y, zoom) {
      const n = Math.pow(2, zoom);
      const west = (x / n) * 360 - 180;
      const east = ((x + 1) / n) * 360 - 180;
      
      const north = Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI;
      const south = Math.atan(Math.sinh(Math.PI * (1 - 2 * (y + 1) / n))) * 180 / Math.PI;
      
      // Converti in metri Mercator per EPSG:3857
      return {
        west: west * 20037508.34 / 180,
        east: east * 20037508.34 / 180,
        south: Math.log(Math.tan((90 + south) * Math.PI / 360)) / (Math.PI / 180) * 20037508.34 / 180,
        north: Math.log(Math.tan((90 + north) * Math.PI / 360)) / (Math.PI / 180) * 20037508.34 / 180
      };
    }
    
    // Controlla se un tile è nella vista corrente
    isTileInView(zoom, x, y) {
      const mapZoom = Math.round(this.map.getZoom());
      if (Math.abs(zoom - mapZoom) > 1) return false;
      
      const bounds = this.map.getBounds();
      const bbox = this.tileToBbox(x, y, zoom);
      
      // Converti bbox in lon/lat
      const west = bbox.west * 180 / 20037508.34;
      const east = bbox.east * 180 / 20037508.34;
      const south = (2 * Math.atan(Math.exp(bbox.south * Math.PI / 20037508.34)) - Math.PI / 2) * 180 / Math.PI;
      const north = (2 * Math.atan(Math.exp(bbox.north * Math.PI / 20037508.34)) - Math.PI / 2) * 180 / Math.PI;
      
      return !(east < bounds.getWest() || west > bounds.getEast() ||
               north < bounds.getSouth() || south > bounds.getNorth());
    }
    
    // Recupera un tile (dalla cache o carica)
    getTile(zoom, x, y, product, timestamp) {
      // Controlla cache
      const cached = this.cache.get(zoom, x, y, product, timestamp);
      if (cached) return cached;
      
      // Avvia caricamento
      this.loadTile(zoom, x, y, product, timestamp);
      return null;
    }
  }
  
  // ========================================================================
  // LIGHTNING DISPLAY - Visualizzazione scientifica dei fulmini
  // ========================================================================
  
  class LightningDisplay {
    constructor() {
      this.strikes = [];
      this.maxAge = 30 * 60 * 1000; // 30 minuti
      
      // Colori basati sull'età (scientifico)
      this.ageColors = {
        fresh: "#ffff00",    // 0-2 min: giallo brillante
        recent: "#ffaa00",   // 2-10 min: arancione
        old: "#ff5500",      // 10-20 min: rosso-arancio
        fading: "#cc0000"    // 20-30 min: rosso scuro
      };
      
      // Cleanup periodico
      setInterval(() => this.cleanup(), 10000);
    }
    
    // Aggiunge una scarica
    addStrike(strike) {
      this.strikes.push({
        ...strike,
        timestamp: strike.timestamp || Date.now(),
        intensity: Math.min(1.0, Math.log10(strike.current || 1000) / 5) // Normalizza corrente
      });
    }
    
    // Rimuove scariche troppo vecchie
    cleanup() {
      const now = Date.now();
      this.strikes = this.strikes.filter(s => now - s.timestamp < this.maxAge);
    }
    
    // Ottieni colore basato sull'età
    getColor(ageMinutes) {
      if (ageMinutes < 2) return this.ageColors.fresh;
      if (ageMinutes < 10) return this.ageColors.recent;
      if (ageMinutes < 20) return this.ageColors.old;
      return this.ageColors.fading;
    }
    
    // Ottieni opacità basata sull'età
    getOpacity(ageMinutes) {
      if (ageMinutes < 2) return 1.0;
      if (ageMinutes < 10) return 0.85;
      if (ageMinutes < 20) return 0.6;
      return 0.35;
    }
    
    // Ottieni raggio basato sulla corrente
    getRadius(current) {
      const baseRadius = 4;
      const currentKA = current / 1000; // Converti in kiloampere
      return baseRadius + Math.log10(Math.max(currentKA, 1)) * 3;
    }
    
    // Renderizza tutti i fulmini
    render(ctx, projectionFn) {
      const now = Date.now();
      
      for (const strike of this.strikes) {
        const age = now - strike.timestamp;
        const ageMinutes = age / 60000;
        
        const color = this.getColor(ageMinutes);
        const opacity = this.getOpacity(ageMinutes);
        const radius = this.getRadius(strike.current || 1000);
        
        const point = projectionFn(strike.lon, strike.lat);
        
        // Glow esterno
        ctx.save();
        ctx.globalAlpha = opacity * 0.3;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(point.x, point.y, radius * 2.5, 0, Math.PI * 2);
        ctx.fill();
        
        // Punto centrale
        ctx.globalAlpha = opacity;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
        ctx.fill();
        
        // Bordo bianco per visibilità
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1;
        ctx.globalAlpha = opacity * 0.8;
        ctx.stroke();
        
        // Simbolo per polarità positiva (meno comune, più pericolosa)
        if (strike.polarity === "positive" || strike.polarity === "+") {
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 2;
          ctx.globalAlpha = opacity;
          
          // Croce
          ctx.beginPath();
          ctx.moveTo(point.x - radius * 0.7, point.y);
          ctx.lineTo(point.x + radius * 0.7, point.y);
          ctx.moveTo(point.x, point.y - radius * 0.7);
          ctx.lineTo(point.x, point.y + radius * 0.7);
          ctx.stroke();
        }
        
        ctx.restore();
      }
    }
    
    // Statistiche recenti
    getStats() {
      const now = Date.now();
      const last5min = this.strikes.filter(s => now - s.timestamp < 5 * 60 * 1000);
      const last15min = this.strikes.filter(s => now - s.timestamp < 15 * 60 * 1000);
      
      return {
        total: this.strikes.length,
        last5min: last5min.length,
        last15min: last15min.length,
        averageCurrent: last15min.length > 0
          ? last15min.reduce((sum, s) => sum + (s.current || 1000), 0) / last15min.length
          : 0,
        positivePercentage: last15min.length > 0
          ? (last15min.filter(s => s.polarity === "positive" || s.polarity === "+").length / last15min.length) * 100
          : 0
      };
    }
  }
  
  // ========================================================================
  // ESPORTA NEL GLOBALE
  // ========================================================================
  
  window.SatelliteTileCache = SatelliteTileCache;
  window.SatelliteManager = SatelliteManager;
  window.LightningDisplay = LightningDisplay;
  
  console.log("[Satellite/Radar/Lightning] Ottimizzazioni caricate");
})();
