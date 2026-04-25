/**
 * FloodSentry — Main Application
 * Task 6: Full Frontend ↔ Backend Integration
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
import type { RegionImpact, ImpactSummary, Infrastructure, Prediction } from './api.ts';

// ── State ──────────────────────────────────────────────────────
let impactSummary: ImpactSummary | null = null;
let activeHazard = 'all';
let map: FloodSentryMap;
let locationCoords: Map<string, { lat: number; lon: number }> = new Map();

// ── DOM Refs ───────────────────────────────────────────────────
const regionsList     = document.getElementById('regions-list')!;
const regionDetail    = document.getElementById('region-detail')!;
const statRegions     = document.getElementById('stat-regions')!;
const statPop         = document.getElementById('stat-pop')!;
const statHospitals   = document.getElementById('stat-hospitals')!;
const statSchools     = document.getElementById('stat-schools')!;
const btnLocate       = document.getElementById('btn-locate')!;
const btnCloseDetail  = document.getElementById('btn-close-detail')!;
const btnZoomIn       = document.getElementById('btn-zoom-in')!;
const btnZoomOut      = document.getElementById('btn-zoom-out')!;
const btnResetView    = document.getElementById('btn-reset-view')!;
const btnToggle3D     = document.getElementById('btn-toggle-3d')!;
const hazardBtns      = document.querySelectorAll<HTMLButtonElement>('.hazard-btn');
const canvas          = document.getElementById('deck-canvas') as HTMLCanvasElement;
const mapContainer    = document.getElementById('map-container')!;

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

    // ── Task 6 Step 3: Auto-display infrastructure for critical regions ──
    const criticalInfra = await api.getCriticalInfrastructure(impactSummary.regions);
    map.updateCriticalInfrastructure(criticalInfra);

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

// ── Boot ───────────────────────────────────────────────────────
init();
