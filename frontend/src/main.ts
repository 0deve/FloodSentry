/**
 * FloodSentry — Main Application
 *
 * Orchestrates:
 * - API data fetching (impact summary, predictions, infrastructure)
 * - NUTS-3 ↔ NUTS-2 mapping for GeoJSON
 * - Sidebar UI with narrative impact display
 * - Auto-infrastructure markers for critical regions
 * - Map rendering and interactions
 */

import './style.css';
import { api, HAZARD_LABELS, HAZARD_SOURCES } from './api.ts';
import { FloodSentryMap } from './map.ts';
import type { RegionImpact, ImpactSummary, Infrastructure, Prediction, AlertRecord, SimulationTimeline } from './api.ts';
import { jsPDF } from 'jspdf';

// State
let impactSummary: ImpactSummary | null = null;
let activeHazard = 'all';
let map: FloodSentryMap;
let locationCoords: Map<string, { lat: number; lon: number }> = new Map();
let currentRegion: RegionImpact | null = null;
let currentAlerts: AlertRecord[] = [];
let simTimeline: SimulationTimeline | null = null;
let simPlaying = false;
let simInterval: ReturnType<typeof setInterval> | null = null;
let logoDataUrl: string = ''; // Pre-loaded for PDF export

// DOM Refs
const regionsList     = document.getElementById('regions-list')!;
const regionDetail    = document.getElementById('region-detail')!;
const statRegions     = document.getElementById('stat-regions')!;
const statPop         = document.getElementById('stat-pop')!;
const statHospitals   = document.getElementById('stat-hospitals')!;
const statSchools     = document.getElementById('stat-schools')!;
const btnLocate       = document.getElementById('btn-locate')!;
const btnBadWeather   = document.getElementById('btn-bad-weather')!;
const btnResetData    = document.getElementById('btn-reset-data')!;
const btnCloseDetail  = document.getElementById('btn-close-detail')!;
const btnZoomIn       = document.getElementById('btn-zoom-in')!;
const btnZoomOut      = document.getElementById('btn-zoom-out')!;
const btnResetView    = document.getElementById('btn-reset-view')!;
const btnToggle3D     = document.getElementById('btn-toggle-3d')!;
const hazardBtns      = document.querySelectorAll<HTMLButtonElement>('.hazard-btn');
const canvas          = document.getElementById('deck-canvas') as HTMLCanvasElement;
const mapContainer    = document.getElementById('map-container')!;
const btnCapXml       = document.getElementById('btn-cap-xml')!;
const btnPdfReport    = document.getElementById('btn-pdf-report')!;
const btnOpenSim      = document.getElementById('btn-open-sim')!;
const simPanel        = document.getElementById('simulator-panel')!;
const btnCloseSim     = document.getElementById('btn-close-sim')!;
const btnSimPlay      = document.getElementById('btn-sim-play')!;
const simSlider       = document.getElementById('sim-slider') as HTMLInputElement;
const simTimeLabel    = document.getElementById('sim-time-label')!;
const simRainfall     = document.getElementById('sim-rainfall') as HTMLInputElement;
const simRainValue    = document.getElementById('sim-rain-value')!;
const simStormType    = document.getElementById('sim-storm-type') as HTMLSelectElement;
const simRegionsEl    = document.getElementById('sim-regions')!;
const simDescText     = document.getElementById('sim-desc-text')!;
const simScenario     = document.getElementById('sim-scenario')!;

// ── Image Helpers ──────────────────────────────────────────────
async function getBase64Image(url: string): Promise<string> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      // Scale up for better quality in PDF
      canvas.width = img.width * 2;
      canvas.height = img.height * 2;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        const dataUrl = canvas.toDataURL('image/png');
        console.log(`[FloodSentry] Logo pre-loaded: ${url}`);
        resolve(dataUrl);
      } else {
        resolve('');
      }
    };
    img.onerror = () => {
      console.error(`[FloodSentry] Failed to load logo: ${url}`);
      resolve('');
    };
    img.src = url;
  });
}

// ── Helpers ────────────────────────────────────────────────────
function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

function alertLevelLabel(level: string): string {
  const labels: Record<string, string> = {
    emergency: 'EMERGENCY',
    critical:  'CRITICAL RISK',
    warning:   'WARNING',
    info:      'LOW RISK',
  };
  return labels[level] ?? level.toUpperCase();
}

function infraTypeIcon(type: string): string {
  const icons: Record<string, string> = {
    hospital: '🏥',
    school: '🏫',
    power_station: '⚡',
    road: '🛣️',
  };
  return icons[type] ?? '📍';
}

function hazardIcon(type: string): string {
  const icons: Record<string, string> = {
    fluvial: '🌊',
    pluvial: '🌧️',
    snowmelt: '❄️',
  };
  return icons[type] ?? '⚠️';
}

// ── Update Stats Bar ───────────────────────────────────────────
function updateStatsBar(summary: ImpactSummary): void {
  animateNumber(statRegions, summary.total_regions_at_risk);
  statPop.textContent = formatNumber(summary.total_affected_population);
  animateNumber(statHospitals, summary.total_hospitals_at_risk);
  animateNumber(statSchools, summary.total_schools_at_risk);
}

function animateNumber(el: HTMLElement, target: number): void {
  const start = parseInt(el.textContent?.replace(/\D/g, '') ?? '0', 10) || 0;
  const duration = 600;
  const startTime = performance.now();
  const step = (now: number) => {
    const progress = Math.min((now - startTime) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(start + (target - start) * eased).toString();
    if (progress < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ── Render Region List ─────────────────────────────────────────
function renderRegionList(regions: RegionImpact[]): void {
  const filtered = activeHazard === 'all'
    ? regions
    : regions.filter(r => r.hazard_type === activeHazard);

  if (filtered.length === 0) {
    regionsList.innerHTML = `<p style="color:var(--text-muted);font-size:12px;text-align:center;padding:20px">No regions match this filter.</p>`;
    return;
  }

  regionsList.innerHTML = '';
  filtered.forEach((region, idx) => {
    const card = document.createElement('div');
    card.className = `region-card ${region.alert_level}`;
    card.style.animationDelay = `${idx * 50}ms`;
    card.dataset['nutsId'] = region.nuts_id;

    const fillColor = riskColor(region.risk_score);
    const infraCount = region.infrastructure_at_risk.reduce((sum, i) => sum + i.count, 0);

    card.innerHTML = `
      <div class="region-card-header">
        <div>
          <div class="region-name">${region.region_name}</div>
          <div class="region-nuts">${region.nuts_id}</div>
        </div>
        <div class="risk-badge ${region.alert_level}">${region.risk_score.toFixed(1)}</div>
      </div>
      <div class="region-card-body">
        <span class="card-pop">${hazardIcon(region.hazard_type)} ${formatNumber(region.affected_population)} affected</span>
        ${infraCount > 0 ? `<span class="card-infra">🏗️ ${infraCount} assets at risk</span>` : ''}
      </div>
      <div class="region-card-footer">
        <span class="hazard-tag ${region.hazard_type}">${region.hazard_type}</span>
        <div class="mini-risk-bar">
          <div class="mini-risk-fill" style="width:${region.risk_score}%;background:${fillColor}"></div>
        </div>
      </div>
    `;

    card.addEventListener('click', () => openRegionDetail(region));
    regionsList.appendChild(card);
  });
}

function riskColor(score: number): string {
  if (score >= 85) return '#7c3aed';
  if (score >= 60) return '#ef4444';
  if (score >= 30) return '#f59e0b';
  return '#22c55e';
}

// ── Build Impact Narrative ─────────────────────────────────────
function buildImpactNarrative(
  region: RegionImpact,
  prediction: Prediction | null,
): string {
  const parts: string[] = [];

  // Flood source
  const source = HAZARD_LABELS[region.hazard_type] ?? region.hazard_type;
  parts.push(`<div class="narrative-section">
    <div class="narrative-label">Flood Source</div>
    <div class="narrative-value">${hazardIcon(region.hazard_type)} ${source}</div>
    <div class="narrative-desc">${HAZARD_SOURCES[region.hazard_type] ?? ''}</div>
  </div>`);

  // Sensor data (from prediction)
  if (prediction) {
    const sensors: string[] = [];
    if (prediction.rainfall_mm != null) sensors.push(`<span class="sensor-chip">🌧️ Rainfall: ${prediction.rainfall_mm.toFixed(1)} mm</span>`);
    if (prediction.soil_moisture != null) sensors.push(`<span class="sensor-chip">🌱 Soil Moisture: ${(prediction.soil_moisture * 100).toFixed(0)}%</span>`);
    if (prediction.river_discharge != null) sensors.push(`<span class="sensor-chip">🌊 River Discharge: ${prediction.river_discharge.toFixed(0)} m³/s</span>`);
    if (prediction.ndwi != null) sensors.push(`<span class="sensor-chip">🛰️ NDWI: ${prediction.ndwi.toFixed(2)}</span>`);
    if (prediction.snow_water_equivalent != null) sensors.push(`<span class="sensor-chip">❄️ Snow Water: ${prediction.snow_water_equivalent.toFixed(1)} mm</span>`);
    if (prediction.temperature_c != null) sensors.push(`<span class="sensor-chip">🌡️ Temp: ${prediction.temperature_c.toFixed(1)}°C</span>`);

    if (sensors.length > 0) {
      parts.push(`<div class="narrative-section">
        <div class="narrative-label">Copernicus Sensor Data</div>
        <div class="sensor-grid">${sensors.join('')}</div>
      </div>`);
    }
  }

  // Impact estimate — population & infrastructure
  const infraParts: string[] = [];
  for (const item of region.infrastructure_at_risk) {
    if (item.count === 1 && item.names.length > 0) {
      infraParts.push(`${infraTypeIcon(item.type)} ${item.names[0]}`);
    } else if (item.count > 0) {
      infraParts.push(`${infraTypeIcon(item.type)} ${item.count} ${item.type}${item.count > 1 ? 's' : ''}${item.names.length > 0 ? ' (' + item.names.slice(0, 2).join(', ') + (item.names.length > 2 ? '…' : '') + ')' : ''}`);
    }
  }

  parts.push(`<div class="narrative-section">
    <div class="narrative-label">Estimated Impact</div>
    <div class="narrative-impact">
      <div class="impact-row"><span class="impact-icon">👥</span><span>Population: <strong>${formatNumber(region.affected_population)}</strong></span></div>
      ${infraParts.map(p => `<div class="impact-row"><span>${p}</span></div>`).join('')}
    </div>
  </div>`);

  // Model info
  if (prediction?.model_version) {
    parts.push(`<div class="narrative-section narrative-meta">
      <span>Model: ${prediction.model_version}</span>
      <span>Predicted: ${new Date(prediction.predicted_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
    </div>`);
  }

  return parts.join('');
}

// ── Open Region Detail ─────────────────────────────────────────
async function openRegionDetail(region: RegionImpact): Promise<void> {
  // Track current region for export actions
  currentRegion = region;

  // Tell map to highlight this region
  map.setSelectedRegion(region.nuts_id);

  // Highlight selected card
  document.querySelectorAll('.region-card').forEach(el => el.classList.remove('selected'));
  const card = document.querySelector(`[data-nuts-id="${region.nuts_id}"]`);
  card?.classList.add('selected');

  // Fill detail panel
  const badge = document.getElementById('detail-alert-badge')!;
  badge.textContent = alertLevelLabel(region.alert_level);
  badge.className = `badge-${region.alert_level}`;

  document.getElementById('detail-name')!.textContent = region.region_name;
  document.getElementById('detail-nuts-id')!.textContent = region.nuts_id;

  const gaugeFill = document.getElementById('gauge-fill')!;
  gaugeFill.style.width = '0%';
  gaugeFill.style.background = `linear-gradient(90deg, ${riskColor(0)}, ${riskColor(region.risk_score)})`;
  setTimeout(() => { gaugeFill.style.width = `${region.risk_score}%`; }, 50);
  document.getElementById('gauge-score')!.textContent = `${region.risk_score.toFixed(1)}`;

  document.getElementById('detail-pop')!.textContent = formatNumber(region.affected_population);
  document.getElementById('detail-hazard')!.textContent = region.hazard_type.charAt(0).toUpperCase() + region.hazard_type.slice(1);

  // Infrastructure
  const infraList = document.getElementById('infra-list')!;
  infraList.innerHTML = '<div class="loading-skeleton" style="height:36px;margin-bottom:4px"></div>';

  // Show detail panel
  regionDetail.classList.remove('hidden');

  // Narrative — loading state
  const narrativeEl = document.getElementById('detail-narrative')!;
  narrativeEl.innerHTML = '<div class="loading-skeleton" style="height:80px"></div>';

  // Summary text
  const summaryBox = document.getElementById('detail-summary-box')!;
  document.getElementById('detail-summary-text')!.textContent = region.summary_text;

  // Update border color based on alert level
  const borderColors: Record<string, string> = {
    emergency: 'var(--risk-emergency)',
    critical:  'var(--risk-critical)',
    warning:   'var(--risk-warning)',
    info:      'var(--risk-low)',
  };
  summaryBox.style.borderLeftColor = borderColors[region.alert_level] ?? 'var(--accent)';

  // Fly camera to region
  const coords = locationCoords.get(region.nuts_id);
  if (coords) {
    map.flyTo(coords.lon, coords.lat, 7);
  }

  // Fetch prediction details + infrastructure in parallel
  const [infra, prediction] = await Promise.all([
    api.getInfrastructure(region.nuts_id).catch(() => [] as Infrastructure[]),
    api.getRegionPredictionDetails(region.nuts_id),
  ]);

  // Render infrastructure list
  renderInfraList(infraList, infra);
  map.updateInfrastructure(infra);

  // Render narrative
  narrativeEl.innerHTML = buildImpactNarrative(region, prediction);
}

function renderInfraList(container: HTMLElement, infra: Infrastructure[]): void {
  if (infra.length === 0) {
    container.innerHTML = `<p style="color:var(--text-muted);font-size:12px">No infrastructure data for this region.</p>`;
    return;
  }
  container.innerHTML = infra.map(item => `
    <div class="infra-item">
      <span class="infra-icon">${infraTypeIcon(item.type)}</span>
      <span class="infra-name">${item.name}</span>
      <span class="infra-type">${item.type.replace('_', ' ')}</span>
    </div>
  `).join('');
}

// ── Hazard Filter ──────────────────────────────────────────────
hazardBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    hazardBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeHazard = btn.dataset['hazard'] ?? 'all';
    if (impactSummary) renderRegionList(impactSummary.regions);
  });
});

// ── Map Controls ───────────────────────────────────────────────
btnZoomIn.addEventListener('click', () => map.zoomIn());
btnZoomOut.addEventListener('click', () => map.zoomOut());
btnResetView.addEventListener('click', () => map.resetView());
btnToggle3D.addEventListener('click', () => {
  const is3D = map.toggle3D();
  btnToggle3D.classList.toggle('active', is3D);
  btnToggle3D.textContent = is3D ? '3D' : '2D';
});

// ── Back button ────────────────────────────────────────────────
btnCloseDetail.addEventListener('click', () => {
  regionDetail.classList.add('hidden');
  document.querySelectorAll('.region-card').forEach(el => el.classList.remove('selected'));
  map.updateInfrastructure([]); // Clear selected region icons from map
  map.setSelectedRegion(null);  // Remove highlight
  map.resetView(); // Fly back to overview
});

// ── Reset Data ──────────────────────────────────────────────────
btnResetData.addEventListener('click', async () => {
  btnResetData.textContent = '⏳ Resetting…';
  btnResetData.setAttribute('disabled', 'true');
  
  try {
    showNotification('Resetting to live conditions...', 'info');
    await api.triggerRefresh(false);
    window.location.reload();
  } catch (err) {
    console.error(err);
    alert('Failed to reset data.');
    btnResetData.innerHTML = '<span>🔄</span> Reset Data';
    btnResetData.removeAttribute('disabled');
  }
});

// ── Test Bad Weather (Now starts the 7-Day EU Simulator) ──────────
btnBadWeather.addEventListener('click', async () => {
  btnBadWeather.textContent = '⏳ Preparing...';
  
  try {
    showNotification('Generating 7-Day Europe Storm Simulation...', 'info');
    simPanel.classList.remove('hidden');
    btnOpenSim.classList.add('active');
    
    await loadSimulation();
    startSimulation();
  } catch (err) {
    console.error(err);
    alert('Failed to start simulation.');
  }
  
  btnBadWeather.innerHTML = '<span>⛈️</span> Test Bad Weather';
});

// ── Locate Me (Galileo) ────────────────────────────────────────
btnLocate.addEventListener('click', () => {
  if (!navigator.geolocation) {
    alert('Geolocation is not supported by your browser.');
    return;
  }
  btnLocate.textContent = '⏳ Locating…';
  btnLocate.setAttribute('disabled', 'true');

  navigator.geolocation.getCurrentPosition(
    pos => {
      const { longitude, latitude } = pos.coords;
      map.flyTo(longitude, latitude, 9);
      btnLocate.innerHTML = '<span>📍</span> Locate Me';
      btnLocate.removeAttribute('disabled');
    },
    () => {
      btnLocate.innerHTML = '<span>📍</span> Locate Me';
      btnLocate.removeAttribute('disabled');
      alert('Could not get your location. Please allow location access.');
    },
    { timeout: 8000, enableHighAccuracy: true },
  );
});

// ── Main Init ──────────────────────────────────────────────────
async function init(): Promise<void> {
  // Initialize 3D map
  map = new FloodSentryMap(canvas, mapContainer);
  await map.init((nutsId: string) => {
    const region = impactSummary?.regions.find(r => r.nuts_id === nutsId);
    if (region) openRegionDetail(region);
  });

  // Toggle 3D button active by default
  btnToggle3D.classList.add('active');

  try {
    // Pre-load logo for PDF
    logoDataUrl = await getBase64Image('/floodsentrylogoblue.svg');

    // Load locations for coordinates (needed for flyTo)
    const locations = await api.getLocations();
    locations.forEach(loc => {
      locationCoords.set(loc.nuts_id, { lat: loc.latitude, lon: loc.longitude });
    });

    // Load impact summary
    impactSummary = await api.getImpactSummary(0); // min_risk=0 to get all
    updateStatsBar(impactSummary);
    renderRegionList(impactSummary.regions);
    map.update(impactSummary.regions);

    // Auto-display infrastructure for critical regions
    const criticalInfra = await api.getCriticalInfrastructure(impactSummary.regions);
    map.updateCriticalInfrastructure(criticalInfra);

    // Auto-generate alerts via Alert Engine
    try {
      await api.evaluateAlerts();
    } catch { /* ignore */ }
    
    // Load all active alerts
    try {
      currentAlerts = await api.getAlerts();
      console.log(`[FloodSentry] ${currentAlerts.length} active alerts loaded.`);
    } catch {
      currentAlerts = [];
    }

    console.log(`[FloodSentry] Loaded ${impactSummary.regions.length} regions, ${criticalInfra.size} critical with infrastructure`);

  } catch (err) {
    console.error('Failed to load FloodSentry data:', err);
    regionsList.innerHTML = `
      <div style="padding:20px;text-align:center;color:var(--text-muted)">
        <p style="font-size:18px;margin-bottom:8px">⚠️</p>
        <p style="font-size:13px">Could not connect to backend.<br>
        Start the server: <code style="font-size:11px;background:var(--bg-elevated);padding:2px 6px;border-radius:3px">uvicorn app.main:app</code></p>
      </div>
    `;
    // Hide map loading even on error
    document.getElementById('map-loading')!.classList.add('hidden');
  }
}

// ══════════════════════════════════════════════════════════════════
// CAP XML Download
// ══════════════════════════════════════════════════════════════════

btnCapXml.addEventListener('click', async () => {
  if (!currentRegion) return;

  // Find alert for this region
  let alert = currentAlerts.find(a => a.nuts_id === currentRegion!.nuts_id);

  // If no alert exists, try to load from API
  if (!alert) {
    try {
      const alerts = await api.getAlerts(currentRegion.nuts_id);
      alert = alerts[0];
    } catch { /* ignore */ }
  }

  if (!alert) {
    // Create an alert on the fly
    try {
      const newAlerts = await api.evaluateAlerts();
      alert = newAlerts.find(a => a.nuts_id === currentRegion!.nuts_id);
      if (!alert) {
        const allAlerts = await api.getAlerts(currentRegion.nuts_id);
        alert = allAlerts[0];
      }
    } catch { /* ignore */ }
  }

  if (alert) {
    // Download CAP XML
    const url = api.getCapXmlUrl(alert.id);
    const link = document.createElement('a');
    link.href = url;
    link.download = `FloodSentry_CAP_${alert.nuts_id}.xml`;
    link.click();
  } else {
    // Fallback: show notification
    const risk = currentRegion.risk_score.toFixed(1);
    showNotification(`No active alert for ${currentRegion.nuts_id} (Risk: ${risk}%). Alerts are only generated for regions with risk >= 1%.`, 'warning');
  }
});

// ══════════════════════════════════════════════════════════════════
// PDF Executive Report
// ══════════════════════════════════════════════════════════════════

btnPdfReport.addEventListener('click', () => {
  if (!currentRegion) return;

  const region = currentRegion;
  const doc = new jsPDF();
  const pageWidth = doc.internal.pageSize.getWidth();
  let y = 20;

  // ── Header ──
  if (logoDataUrl) {
    try {
      // Draw blue logo icon
      doc.addImage(logoDataUrl, 'PNG', 20, 12, 12, 14); 
    } catch (e) {
      console.error('PDF Logo Error:', e);
    }
  }
  
  doc.setFontSize(24);
  doc.setFont('helvetica', 'bold');
  doc.setTextColor(20, 41, 86); // Dark blue from logo
  doc.text('FloodSentry', 35, 24);
  
  doc.setFontSize(10);
  doc.setFont('helvetica', 'normal');
  doc.setTextColor(100, 100, 100);
  doc.text('EU Flood Risk Digital Twin — Executive Report', 20, 34);
  doc.text(`Generated: ${new Date().toLocaleString('en-GB')}`, 20, 40);

  // Divider line
  y = 48;
  doc.setDrawColor(20, 41, 86);
  doc.setLineWidth(0.5);
  doc.line(20, y, pageWidth - 20, y);
  y += 12;

  // ── Alert Level Banner ──
  const alertColors: Record<string, [number, number, number]> = {
    emergency: [124, 58, 237],
    critical: [239, 68, 68],
    warning: [245, 158, 11],
    info: [34, 197, 94],
  };
  const alertColor = alertColors[region.alert_level] || [100, 100, 100];
  doc.setFillColor(...alertColor);
  doc.roundedRect(20, y, pageWidth - 40, 14, 3, 3, 'F');
  doc.setTextColor(255, 255, 255);
  doc.setFontSize(12);
  doc.setFont('helvetica', 'bold');
  doc.text(`${alertLevelLabel(region.alert_level)} — ${region.region_name} (${region.nuts_id})`, 26, y + 9);
  y += 22;

  // ── Risk Score ──
  doc.setTextColor(40, 40, 40);
  doc.setFontSize(14);
  doc.setFont('helvetica', 'bold');
  doc.text('Risk Assessment', 20, y);
  y += 8;

  doc.setFontSize(11);
  doc.setFont('helvetica', 'normal');
  const riskData = [
    ['Risk Score', `${region.risk_score.toFixed(1)} / 100`],
    ['Hazard Type', (HAZARD_LABELS[region.hazard_type] || region.hazard_type)],
    ['Affected Population', formatNumber(region.affected_population)],
    ['Alert Level', alertLevelLabel(region.alert_level)],
  ];
  for (const [label, value] of riskData) {
    doc.setFont('helvetica', 'bold');
    doc.text(`${label}:`, 24, y);
    doc.setFont('helvetica', 'normal');
    doc.text(value, 80, y);
    y += 7;
  }
  y += 6;

  // ── Infrastructure at Risk ──
  doc.setFontSize(14);
  doc.setFont('helvetica', 'bold');
  doc.text('Infrastructure at Risk', 20, y);
  y += 8;

  doc.setFontSize(11);
  doc.setFont('helvetica', 'normal');
  if (region.infrastructure_at_risk.length > 0) {
    for (const item of region.infrastructure_at_risk) {
      const typeLabel = item.type.charAt(0).toUpperCase() + item.type.slice(1).replace('_', ' ');
      doc.setFont('helvetica', 'bold');
      doc.text(`• ${item.count} ${typeLabel}${item.count > 1 ? 's' : ''}`, 24, y);
      doc.setFont('helvetica', 'normal');
      if (item.names.length > 0) {
        doc.text(`: ${item.names.slice(0, 4).join(', ')}`, 70, y);
      }
      y += 7;
    }
  } else {
    doc.text('No critical infrastructure data available.', 24, y);
    y += 7;
  }
  y += 6;

  // ── Flood Source Analysis ──
  doc.setFontSize(14);
  doc.setFont('helvetica', 'bold');
  doc.text('Flood Source Analysis', 20, y);
  y += 8;

  doc.setFontSize(11);
  doc.setFont('helvetica', 'normal');
  const sourceDesc = HAZARD_SOURCES[region.hazard_type] || 'Unknown hazard source.';
  const sourceLines = doc.splitTextToSize(sourceDesc, pageWidth - 50);
  doc.text(sourceLines, 24, y);
  y += sourceLines.length * 6 + 6;

  // ── Impact Summary ──
  doc.setFontSize(14);
  doc.setFont('helvetica', 'bold');
  doc.text('Impact Summary', 20, y);
  y += 8;

  doc.setFontSize(11);
  doc.setFont('helvetica', 'normal');
  const summaryLines = doc.splitTextToSize(region.summary_text, pageWidth - 50);
  doc.text(summaryLines, 24, y);
  y += summaryLines.length * 6 + 10;

  // ── Footer ──
  doc.setDrawColor(200, 200, 200);
  doc.setLineWidth(0.3);
  doc.line(20, 275, pageWidth - 20, 275);
  doc.setFontSize(8);
  doc.setTextColor(140, 140, 140);
  doc.text('FloodSentry — CASSINI Hackathon "EU Space for Water" — Powered by Copernicus & Galileo', 20, 280);
  doc.text(`Report ID: FS-${Date.now().toString(36).toUpperCase()} | Classification: OFFICIAL`, 20, 284);

  // Save
  doc.save(`FloodSentry_Report_${region.nuts_id}_${new Date().toISOString().slice(0, 10)}.pdf`);
  showNotification('PDF Report generated successfully!', 'success');
});

// ══════════════════════════════════════════════════════════════════
// Hydrologic Simulator (Time-Slider)
// ══════════════════════════════════════════════════════════════════

btnOpenSim.addEventListener('click', async () => {
  simPanel.classList.toggle('hidden');
  btnOpenSim.classList.toggle('active');

  if (!simPanel.classList.contains('hidden') && !simTimeline) {
    await loadSimulation();
  }
});

btnCloseSim.addEventListener('click', () => {
  simPanel.classList.add('hidden');
  btnOpenSim.classList.remove('active');
  stopSimulation();
  
  // Restore live data map
  if (impactSummary) {
    map.update(impactSummary.regions);
  }
});

async function loadSimulation(): Promise<void> {
  const rainfall = parseInt(simRainfall.value);
  const stormType = simStormType.value;
  try {
    simTimeline = await api.getSimulationTimeline(rainfall, 7, stormType);
    simSlider.max = String(simTimeline.total_steps - 1);
    simSlider.value = '0';
    simScenario.textContent = simTimeline.scenario;
    renderSimStep(0);
  } catch (err) {
    console.error('Failed to load simulation:', err);
    simRegionsEl.innerHTML = '<p style="color:var(--text-muted);font-size:12px;text-align:center">Could not load simulation data.</p>';
  }
}

simStormType.addEventListener('change', () => {
  if (!simPanel.classList.contains('hidden')) {
    loadSimulation();
  }
});

function renderSimStep(stepIndex: number): void {
  if (!simTimeline || stepIndex >= simTimeline.steps.length) return;

  const step = simTimeline.steps[stepIndex];
  simTimeLabel.textContent = step.label;

  // Build region cards (Top 5 only)
  simRegionsEl.innerHTML = step.regions.slice(0, 5).map(r => {
    const fillWidth = Math.min(100, r.risk_score);
    const barColor = riskColor(r.risk_score);
    const activeClass = r.wave_active ? 'sim-wave-active' : '';
    return `
      <div class="sim-region-card ${r.alert_level} ${activeClass}">
        <div class="sim-region-header">
          <span class="sim-region-name">${r.name}</span>
          <span class="sim-region-risk" style="color:${barColor}">${r.risk_score.toFixed(1)}</span>
        </div>
        <div class="sim-risk-bar">
          <div class="sim-risk-fill" style="width:${fillWidth}%;background:${barColor}"></div>
        </div>
        <div class="sim-region-meta">
          <span>${r.wave_active ? '🌊 Storm' : '—'}</span>
          <span>🌧️ ${r.rainfall_mm.toFixed(0)}mm</span>
        </div>
      </div>
    `;
  }).join('');

  // Update map in real-time (and pass rainfall to show clouds)
  const simRegionsAsImpact: RegionImpact[] = step.regions.map(r => ({
    nuts_id: r.nuts_id,
    region_name: r.name,
    risk_score: r.risk_score,
    hazard_type: 'pluvial',
    affected_population: Math.floor(r.risk_score * 2500), // simulated pop
    infrastructure_at_risk: [],
    alert_level: r.alert_level as 'info'|'warning'|'critical'|'emergency',
    summary_text: r.description,
    rainfall_mm: r.rainfall_mm,
    latitude: r.lat,
    longitude: r.lon
  }));
  map.update(simRegionsAsImpact);

  // Description
  const activeRegion = step.regions.find(r => r.risk_score > 60);
  simDescText.textContent = activeRegion?.description || step.regions[0]?.description || 'Monitoring Europe...';
}

btnSimPlay.addEventListener('click', () => {
  if (simPlaying) {
    stopSimulation();
  } else {
    startSimulation();
  }
});

function startSimulation(): void {
  // Clear any existing interval to prevent ghost loops
  if (simInterval) {
    stopSimulation();
  }
  
  simPlaying = true;
  btnSimPlay.textContent = '⏸';
  btnSimPlay.classList.add('playing');

  simInterval = setInterval(() => {
    let current = parseInt(simSlider.value);
    current++;
    if (current >= parseInt(simSlider.max)) {
      current = 0; // Loop
    }
    simSlider.value = String(current);
    renderSimStep(current);
  }, 800);
}

function stopSimulation(): void {
  simPlaying = false;
  btnSimPlay.textContent = '▶';
  btnSimPlay.classList.remove('playing');
  if (simInterval) {
    clearInterval(simInterval);
    simInterval = null;
  }
}

simSlider.addEventListener('input', () => {
  renderSimStep(parseInt(simSlider.value));
});

simRainfall.addEventListener('input', () => {
  simRainValue.textContent = `${simRainfall.value}mm`;
});

simRainfall.addEventListener('change', async () => {
  stopSimulation();
  await loadSimulation();
});

// ── Notification Helper ────────────────────────────────────────
function showNotification(message: string, type: 'success' | 'warning' | 'error' = 'success'): void {
  const existing = document.querySelector('.fs-notification');
  if (existing) existing.remove();

  const el = document.createElement('div');
  el.className = `fs-notification fs-notification-${type}`;
  el.innerHTML = `<span>${type === 'success' ? '✅' : type === 'warning' ? '⚠️' : '❌'}</span> ${message}`;
  document.body.appendChild(el);

  requestAnimationFrame(() => el.classList.add('visible'));
  setTimeout(() => {
    el.classList.remove('visible');
    setTimeout(() => el.remove(), 300);
  }, 3000);
}

// ── Boot ───────────────────────────────────────────────────────
init();
