/* ============================================
   SICILIA METEO - SCIENTIFIC UI ENHANCEMENTS
   Professional interface inspired by Windy/Ventusky
   Focus: ICON-2I model
   ============================================ */

(function() {
  'use strict';

  // ============================================
  // SCIENTIFIC SIDEBAR - Parameter Selection
  // ============================================
  
  const ScientificSidebar = {
    container: null,
    activeLayer: 'temp',
    
    // Parameter definitions with scientific icons
    parameters: [
      { id: 'temp', name: 'Temperatura', unit: '°C', icon: 'temp', tooltip: 'Temperatura a 2m (ICON-2I)' },
      { id: 'wind', name: 'Vento', unit: 'km/h', icon: 'wind', tooltip: 'Vento a 10m (ICON-2I)' },
      { id: 'precip', name: 'Precipitazioni', unit: 'mm', icon: 'rain', tooltip: 'Precipitazioni totali (ICON-2I)' },
      { id: 'cloud', name: 'Nuvolosità', unit: '%', icon: 'cloud', tooltip: 'Copertura nuvolosa (ICON-2I)' },
      { id: 'pressure', name: 'Pressione', unit: 'hPa', icon: 'press', tooltip: 'Pressione MSL (ICON-2I)' },
      { id: 'humidity', name: 'Umidità', unit: '%', icon: 'rh', tooltip: 'Umidità relativa 2m (ICON-2I)' },
      { id: 'cape', name: 'CAPE', unit: 'J/kg', icon: 'cape', tooltip: 'Energia potenziale convettiva (ICON-2I)' },
      { id: 'cin', name: 'CIN', unit: 'J/kg', icon: 'cin', tooltip: 'Energia di inibizione convettiva (ICON-2I)' },
      { id: 'lifted', name: 'Lifted Index', unit: '°C', icon: 'lifted', tooltip: 'Indice di stabilità (ICON-2I)' },
      { id: 'shear', name: 'Bulk Shear', unit: 'm/s', icon: 'shear', tooltip: 'Wind shear 0-6km (ICON-2I)' },
      { id: 'helicity', name: 'Elicità', unit: 'm²/s²', icon: 'helicity', tooltip: 'Elicità 0-3km (ICON-2I)' },
      { id: 'visibility', name: 'Visibilità', unit: 'km', icon: 'visibility', tooltip: 'Visibilità orizzontale (ICON-2I)' }
    ],
    
    init: function() {
      this.createSidebar();
      this.bindEvents();
    },
    
    createSidebar: function() {
      // Create sidebar container
      this.container = document.createElement('div');
      this.container.className = 'scientific-sidebar';
      this.container.id = 'scientific-sidebar';
      
      // Add parameter buttons
      this.parameters.forEach(param => {
        const button = document.createElement('button');
        button.className = 'sidebar-icon-button';
        button.setAttribute('data-layer', param.id);
        button.setAttribute('data-tooltip', param.tooltip);
        button.type = 'button';
        
        // SVG icon based on parameter type
        button.innerHTML = this.getIcon(param.icon);
        
        if (param.id === this.activeLayer) {
          button.classList.add('active');
        }
        
        this.container.appendChild(button);
      });
      
      document.body.appendChild(this.container);
    },
    
    getIcon: function(type) {
      const icons = {
        temp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0Z" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        wind: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M3 8h12a3 3 0 1 0-3-3 M3 12h16a3 3 0 1 1-3 3 M3 16h5" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        rain: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M5 14a4 4 0 0 1 0-8 6 6 0 0 1 11-1 4.5 4.5 0 0 1 1 9 M8 17l-1 3 M13 17l-1 3 M18 17l-1 3" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        cloud: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 17a5 5 0 0 1 0-10 6 6 0 0 1 11-1 5.5 5.5 0 0 1 0 11Z" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        press: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M5 19a9 9 0 1 1 14 0 M12 12l4-4 M4 12h2 M18 12h2" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        rh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 3S5 11 5 15a7 7 0 0 0 14 0c0-4-7-12-7-12Z" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        cape: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 2v20 M4 6l8 4 8-4 M4 18l8-4 8 4" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        cin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 4l16 16 M4 20l16-16" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        lifted: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 2v20 M8 6l4-4 4 4" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        shear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M3 8l18 8 M3 16l18-8" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        helicity: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 2a10 10 0 1 0 10 10 M12 2v20 M12 12h10" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        visibility: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="10" stroke-width="1.8"/><path d="M12 8v4 M12 16h.01" stroke-width="1.8" stroke-linecap="round"/></svg>'
      };
      return icons[type] || icons.temp;
    },
    
    bindEvents: function() {
      this.container.addEventListener('click', (e) => {
        const button = e.target.closest('.sidebar-icon-button');
        if (!button) return;
        
        const layerId = button.getAttribute('data-layer');
        this.setActiveLayer(layerId);
        
        // Trigger layer change in main app
        if (window.setActiveLayer) {
          window.setActiveLayer(layerId);
        }
      });
    },
    
    setActiveLayer: function(layerId) {
      // Update active state
      this.container.querySelectorAll('.sidebar-icon-button').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-layer') === layerId);
      });
      
      this.activeLayer = layerId;
      
      // Update legend
      ScientificLegend.update(layerId);
    }
  };
  
  // ============================================
  // SCIENTIFIC TIMELINE - Time Navigation
  // ============================================
  
  const ScientificTimeline = {
    container: null,
    currentTime: 0,
    totalTime: 72, // 72 hours forecast
    isPlaying: false,
    playInterval: null,
    
    init: function() {
      this.createTimeline();
      this.bindEvents();
    },
    
    createTimeline: function() {
      this.container = document.createElement('div');
      this.container.className = 'scientific-timeline';
      this.container.id = 'scientific-timeline';
      
      // Controls
      const controls = document.createElement('div');
      controls.className = 'timeline-controls';
      
      // Play button
      const playBtn = document.createElement('button');
      playBtn.className = 'timeline-button';
      playBtn.id = 'timeline-play';
      playBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
      controls.appendChild(playBtn);
      
      // Rewind button
      const rewindBtn = document.createElement('button');
      rewindBtn.className = 'timeline-button';
      rewindBtn.id = 'timeline-rewind';
      rewindBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="19 20 9 12 19 4 19 20"/><line x1="5" y1="19" x2="5" y2="5"/></svg>';
      controls.appendChild(rewindBtn);
      
      this.container.appendChild(controls);
      
      // Scrubber
      const scrubber = document.createElement('div');
      scrubber.className = 'timeline-scrubber';
      
      // Track
      const track = document.createElement('div');
      track.className = 'timeline-track';
      track.id = 'timeline-track';
      
      const progress = document.createElement('div');
      progress.className = 'timeline-progress';
      progress.id = 'timeline-progress';
      track.appendChild(progress);
      
      scrubber.appendChild(track);
      
      // Labels
      const labels = document.createElement('div');
      labels.className = 'timeline-labels';
      
      const currentLabel = document.createElement('span');
      currentLabel.className = 'timeline-current';
      currentLabel.id = 'timeline-current';
      currentLabel.textContent = this.formatTime(0);
      labels.appendChild(currentLabel);
      
      const totalLabel = document.createElement('span');
      totalLabel.textContent = `+${this.totalTime}h`;
      labels.appendChild(totalLabel);
      
      scrubber.appendChild(labels);
      this.container.appendChild(scrubber);
      
      document.body.appendChild(this.container);
    },
    
    formatTime: function(hours) {
      const date = new Date();
      date.setHours(date.getHours() + hours);
      return date.toLocaleString('it-IT', { 
        day: '2-digit', 
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      });
    },
    
    bindEvents: function() {
      // Play button
      document.getElementById('timeline-play').addEventListener('click', () => {
        this.togglePlay();
      });
      
      // Rewind button
      document.getElementById('timeline-rewind').addEventListener('click', () => {
        this.rewind();
      });
      
      // Track click
      document.getElementById('timeline-track').addEventListener('click', (e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        const percent = (e.clientX - rect.left) / rect.width;
        this.setTime(Math.round(percent * this.totalTime));
      });
    },
    
    togglePlay: function() {
      this.isPlaying = !this.isPlaying;
      const playBtn = document.getElementById('timeline-play');
      
      if (this.isPlaying) {
        playBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>';
        this.playInterval = setInterval(() => {
          if (this.currentTime < this.totalTime) {
            this.setTime(this.currentTime + 1);
          } else {
            this.rewind();
          }
        }, 1000);
      } else {
        playBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
        clearInterval(this.playInterval);
      }
    },
    
    rewind: function() {
      this.setTime(0);
    },
    
    setTime: function(hours) {
      this.currentTime = Math.max(0, Math.min(hours, this.totalTime));
      
      // Update UI
      const progress = document.getElementById('timeline-progress');
      const currentLabel = document.getElementById('timeline-current');
      
      const percent = (this.currentTime / this.totalTime) * 100;
      progress.style.width = percent + '%';
      currentLabel.textContent = this.formatTime(this.currentTime);
      
      // Trigger time change in main app
      if (window.setForecastTime) {
        window.setForecastTime(this.currentTime);
      }
    }
  };
  
  // ============================================
  // SCIENTIFIC LEGEND - Color Scale Display
  // ============================================
  
  const ScientificLegend = {
    container: null,
    currentLayer: 'temp',
    
    palettes: {
      temp: {
        name: 'Temperatura',
        unit: '°C',
        min: -30,
        max: 40,
        colors: ['#1a3a7a', '#3a7ab8', '#7ab8e0', '#bae0e8', '#dae8c0', '#a0c860', '#ffff80', '#ffa000', '#ff4000', '#e00000']
      },
      wind: {
        name: 'Vento',
        unit: 'km/h',
        min: 0,
        max: 150,
        colors: ['#f0f0f0', '#d0e0e8', '#a0c8d0', '#60a8b0', '#007880', '#005058', '#003840', '#203040', '#402040', '#601040']
      },
      precip: {
        name: 'Precipitazioni',
        unit: 'mm/h',
        min: 0,
        max: 50,
        colors: ['#e0f0e8', '#a0d0b8', '#60b088', '#209058', '#006020', '#403000', '#801000', '#c00000', '#ff0000', '#ffc0c0']
      },
      cloud: {
        name: 'Nuvolosità',
        unit: '%',
        min: 0,
        max: 100,
        colors: ['#f8f8f8', '#e0e0e8', '#c8c8d0', '#b0b0b8', '#9898a0', '#808088', '#686870', '#505058', '#383840', '#202028']
      },
      pressure: {
        name: 'Pressione',
        unit: 'hPa',
        min: 980,
        max: 1040,
        colors: ['#1a2a5a', '#3a4a7a', '#5a6a9a', '#7a8aba', '#9aaada', '#bacaef', '#f0e0f0', '#f0d0e0', '#f0b0c0', '#f090a0']
      },
      humidity: {
        name: 'Umidità Relativa',
        unit: '%',
        min: 0,
        max: 100,
        colors: ['#8b4513', '#a0522d', '#cd853f', '#daa520', '#ffd700', '#adff2f', '#7fff00', '#00ff00', '#00ffff', '#0080ff']
      },
      cape: {
        name: 'CAPE',
        unit: 'J/kg',
        min: 0,
        max: 4000,
        colors: ['#f8f8f8', '#e8e8d8', '#d8d8b8', '#c8c898', '#b8b878', '#a8a858', '#989838', '#888818', '#808008', '#ff9000']
      },
      cin: {
        name: 'CIN',
        unit: 'J/kg',
        min: -500,
        max: 0,
        colors: ['#ff4040', '#ff6060', '#ff8080', '#ffa0a0', '#ffc0c0', '#ffe0e0', '#f8f8f8', '#f0f0f0', '#e8e8e8', '#e0e0e0']
      },
      lifted: {
        name: 'Lifted Index',
        unit: '°C',
        min: -10,
        max: 10,
        colors: ['#ff0000', '#ff4040', '#ff8080', '#ffc0c0', '#f8f8f8', '#c0ffc0', '#80ff80', '#40ff40', '#00ff00', '#00c000']
      },
      shear: {
        name: 'Bulk Shear 0-6km',
        unit: 'm/s',
        min: 0,
        max: 50,
        colors: ['#e0e0e0', '#c0c0e0', '#a0a0e0', '#8080e0', '#6060e0', '#4040e0', '#2020e0', '#0000e0', '#0000c0', '#0000a0']
      },
      helicity: {
        name: 'Elicità 0-3km',
        unit: 'm²/s²',
        min: 0,
        max: 500,
        colors: ['#f0f0f0', '#e0e8f0', '#d0e0e8', '#c0d8e0', '#b0d0d8', '#a0c8d0', '#90c0c8', '#80b8c0', '#70b0b8', '#601040']
      },
      visibility: {
        name: 'Visibilità',
        unit: 'km',
        min: 0,
        max: 20,
        colors: ['#404040', '#606060', '#808080', '#a0a0a0', '#c0c0c0', '#e0e0e0', '#f0f0f0', '#f8f8f8', '#ffffff', '#ffffff']
      }
    },
    
    init: function() {
      this.createLegend();
    },
    
    createLegend: function() {
      this.container = document.createElement('div');
      this.container.className = 'scientific-legend';
      this.container.id = 'scientific-legend';
      
      this.update(this.currentLayer);
      document.body.appendChild(this.container);
    },
    
    update: function(layerId) {
      const palette = this.palettes[layerId] || this.palettes.temp;
      this.currentLayer = layerId;
      
      // Title
      let html = `<div class="legend-title">${palette.name}</div>`;
      
      // Gradient
      const gradientColors = palette.colors.join(', ');
      html += `<div class="legend-gradient" style="background: linear-gradient(to right, ${gradientColors});"></div>`;
      
      // Labels
      html += `<div class="legend-labels">`;
      html += `<span>${palette.min}</span>`;
      html += `<span>${Math.round((palette.min + palette.max) / 2)}</span>`;
      html += `<span>${palette.max}</span>`;
      html += `</div>`;
      
      // Unit
      html += `<div class="legend-unit">${palette.unit}</div>`;
      
      this.container.innerHTML = html;
    }
  };
  
  // ============================================
  // SCIENTIFIC TOOLTIP - Enhanced Hover Info
  // ============================================
  
  const ScientificTooltip = {
    container: null,
    isVisible: false,
    
    init: function() {
      this.createTooltip();
      this.bindEvents();
    },
    
    createTooltip: function() {
      this.container = document.createElement('div');
      this.container.className = 'scientific-tooltip';
      this.container.id = 'scientific-tooltip';
      this.container.style.display = 'none';
      document.body.appendChild(this.container);
    },
    
    bindEvents: function() {
      // Listen for map mouse events from main app
      if (window.map) {
        window.map.on('mousemove', (e) => {
          this.show(e);
        });
        
        window.map.on('mouseout', () => {
          this.hide();
        });
      }
    },
    
    show: function(e) {
      if (!e.lngLat) return;
      
      // Get data for this point (would integrate with main app's data)
      const data = this.getDataForPoint(e.lngLat);
      
      // Build tooltip content
      let html = `<div class="tooltip-header">ICON-2I · ${data.time}</div>`;
      html += `<div class="tooltip-grid">`;
      
      // Add parameters
      Object.keys(data.values).forEach(key => {
        const param = data.values[key];
        html += `<span class="tooltip-label">${param.name}:</span>`;
        html += `<span class="tooltip-value">${param.value} ${param.unit}</span>`;
      });
      
      html += `</div>`;
      html += `<div class="tooltip-coords">${e.lngLat.lat.toFixed(4)}°N, ${e.lngLat.lng.toFixed(4)}°E · ${data.elevation}m</div>`;
      
      this.container.innerHTML = html;
      this.container.style.display = 'block';
      
      // Position tooltip
      const x = e.originalEvent.clientX + 16;
      const y = e.originalEvent.clientY + 16;
      
      // Check if tooltip goes off screen
      const rect = this.container.getBoundingClientRect();
      const adjustedX = x + rect.width > window.innerWidth ? x - rect.width - 32 : x;
      const adjustedY = y + rect.height > window.innerHeight ? y - rect.height - 32 : y;
      
      this.container.style.left = adjustedX + 'px';
      this.container.style.top = adjustedY + 'px';
      
      this.isVisible = true;
    },
    
    hide: function() {
      this.container.style.display = 'none';
      this.isVisible = false;
    },
    
    getDataForPoint: function(lngLat) {
      // This would integrate with the main app's data source
      // For now, return mock data
      return {
        time: new Date().toLocaleString('it-IT', { hour: '2-digit', minute: '2-digit' }),
        elevation: Math.round(Math.random() * 500),
        values: {
          temp: { name: 'Temperatura', value: (Math.random() * 30 - 5).toFixed(1), unit: '°C' },
          wind: { name: 'Vento', value: Math.round(Math.random() * 50), unit: 'km/h' },
          humidity: { name: 'Umidità', value: Math.round(Math.random() * 100), unit: '%' },
          pressure: { name: 'Pressione', value: (1013 + (Math.random() * 20 - 10)).toFixed(1), unit: 'hPa' }
        }
      };
    }
  };
  
  // ============================================
  // INITIALIZATION
  // ============================================
  
  // Wait for DOM to be ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  
  function init() {
    // Initialize all UI components
    ScientificSidebar.init();
    ScientificTimeline.init();
    ScientificLegend.init();
    ScientificTooltip.init();
    
    // Expose to global scope for integration
    window.ScientificUI = {
      sidebar: ScientificSidebar,
      timeline: ScientificTimeline,
      legend: ScientificLegend,
      tooltip: ScientificTooltip
    };
    
    console.log('Scientific UI initialized - ICON-2I focus');
  }
  
})();
