/**
 * FloodSentry — Deck.gl 3D Digital Twin Map
 * Task 6: Full integration — NUTS GeoJSON ↔ predictions ↔ infrastructure.
 *
 * - Renders NUTS-2 extruded polygons colored by aggregated risk
 * - Automatically shows infrastructure markers for critical/emergency regions
 * - Tooltips with risk & hazard detail
 */

import type { RegionImpact, Infrastructure } from './api.ts';
import { nutsToLevel2, isChildOf } from './api.ts';

// ── Deck.gl / MapLibre imports ────────────────────────────────
import { Deck } from '@deck.gl/core';
import { GeoJsonLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import type { Layer } from '@deck.gl/core';

// ── Constants ─────────────────────────────────────────────────
const INITIAL_VIEW_STATE = {
  longitude: 26.0,
  latitude: 46.0,
  zoom: 5.5,
  pitch: 50,
  bearing: -10,
  transitionDuration: 1000,
};

// const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

// ── Risk Color Mapping ─────────────────────────────────────────
function riskToColor(score: number): [number, number, number, number] {
  if (score >= 85) return [124, 58, 237, 220];   // Emergency — Purple
  if (score >= 60) return [239, 68, 68, 210];    // Critical — Red
  if (score >= 30) return [245, 158, 11, 190];   // Warning — Amber
  return [34, 197, 94, 160];                       // Info — Green
}

function riskToLineColor(score: number): [number, number, number, number] {
  if (score >= 85) return [167, 139, 250, 255];
  if (score >= 60) return [248, 113, 113, 255];
  if (score >= 30) return [251, 191, 36, 255];
  return [74, 222, 128, 255];
}

// Infrastructure markers — color by type
function infraMarkerColor(type: string): [number, number, number, number] {
  const colors: Record<string, [number, number, number, number]> = {
    hospital:      [255, 100, 100, 230],  // Red cross
    school:        [100, 180, 255, 230],  // Blue
    power_station: [255, 200, 60, 230],   // Yellow
    road:          [180, 180, 180, 200],  // Grey
  };
  return colors[type] ?? [255, 255, 255, 200];
}

function infraMarkerRadius(type: string): number {
  const sizes: Record<string, number> = {
    hospital:      600,
    school:        450,
    power_station: 500,
    road:          400,
  };
  return sizes[type] ?? 400;
}

// Infrastructure icon mapping
function infraIcon(type: string): string {
  const icons: Record<string, string> = {
    hospital:      '🏥',
    school:        '🏫',
    power_station: '⚡',
    road:          '🛣️',
  };
  return icons[type] ?? '📍';
}

// ── NUTS-2 Aggregated Risk ─────────────────────────────────────
/** Aggregate NUTS-3 region data to the NUTS-2 GeoJSON level */
function aggregateToNuts2(regionData: Map<string, RegionImpact>): Map<string, RegionImpact> {
  const nuts2Map = new Map<string, RegionImpact>();

  for (const [nuts3Id, region] of regionData.entries()) {
    const nuts2Id = nutsToLevel2(nuts3Id);

    if (!nuts2Map.has(nuts2Id)) {
      // Initialize with first child's data
      nuts2Map.set(nuts2Id, { ...region, nuts_id: nuts2Id });
    } else {
      const existing = nuts2Map.get(nuts2Id)!;
      // Keep the highest risk score
      if (region.risk_score > existing.risk_score) {
        nuts2Map.set(nuts2Id, {
          ...region,
          nuts_id: nuts2Id,
          affected_population: existing.affected_population + region.affected_population,
        });
      } else {
        existing.affected_population += region.affected_population;
      }
    }
  }

  return nuts2Map;
}

// ── Map Class ─────────────────────────────────────────────────
export class FloodSentryMap {
  private deck: Deck | null = null;
  private viewState = { ...INITIAL_VIEW_STATE };
  private is3D = true;
  private nutsGeoJson: object | null = null;
  private regionData: Map<string, RegionImpact> = new Map();
  private nuts2Data: Map<string, RegionImpact> = new Map();
  private onRegionClick: ((nuts_id: string) => void) | null = null;
  private tooltipEl: HTMLElement;
  private loadingEl: HTMLElement;
  // Infrastructure — selected region (detail view)
  private selectedInfraData: Infrastructure[] = [];
  // Infrastructure — all critical regions (auto-display on map)
  private criticalInfraData: Map<string, Infrastructure[]> = new Map();
  private selectedNutsId: string | null = null;

  private canvasEl: HTMLCanvasElement;

  constructor(
    canvasEl: HTMLCanvasElement,
    _containerEl: HTMLElement,
  ) {
    this.canvasEl = canvasEl;
    this.tooltipEl = document.getElementById('map-tooltip')!;
    this.loadingEl = document.getElementById('map-loading')!;
  }

  async init(onRegionClick: (nuts_id: string) => void): Promise<void> {
    this.onRegionClick = onRegionClick;

    // Load NUTS GeoJSON (served via Vite's public dir or from backend data)
    try {
      // Try to load from the backend data folder via API proxy, or fall back to minimal inline
      const response = await fetch('/nuts_regions.geojson');
      if (response.ok) {
        this.nutsGeoJson = await response.json();
      }
    } catch {
      console.warn('Could not load NUTS GeoJSON — map will use scatter points only.');
    }

    this.deck = new Deck({
      canvas: this.canvasEl,
      initialViewState: this.viewState,
      controller: true,
      onViewStateChange: ({ viewState }: any) => {
        this.viewState = viewState;
      },
      layers: [],
      getTooltip: () => null, // we handle tooltip manually
      onHover: (info: any) => {
        this.handleHover(info);
      },
      onClick: (info: any) => {
        this.handleClick(info);
      },
    });

    // Hide loading after deck initializes
    setTimeout(() => {
      this.loadingEl.classList.add('hidden');
    }, 800);
  }

  /** Handle click on map features */
  private handleClick(info: any): void {
    if (!info.object || !this.onRegionClick) return;

    const layerId = info.layer?.id;

    if (layerId === 'nuts-regions') {
      // GeoJSON layer uses NUTS_ID (level 2)
      const nuts2Id = (info.object as { properties?: { NUTS_ID?: string } }).properties?.NUTS_ID;
      if (nuts2Id) {
        // Find the best matching NUTS-3 region
        const nuts3Id = this.findBestNuts3ForNuts2(nuts2Id);
        if (nuts3Id) {
          this.onRegionClick(nuts3Id);
        }
      }
    } else if (layerId === 'critical-infra-scatter' || layerId === 'selected-infra-icons') {
      // Clicking infrastructure — find the parent region
      const infraItem = info.object as unknown as Infrastructure;
      if (infraItem?.nuts_id) {
        this.onRegionClick(infraItem.nuts_id);
      }
    }
  }

  /** Find the best NUTS-3 region that belongs to a NUTS-2 parent */
  private findBestNuts3ForNuts2(nuts2Id: string): string | null {
    let bestId: string | null = null;
    let bestScore = -1;

    for (const [nuts3Id, region] of this.regionData.entries()) {
      if (isChildOf(nuts3Id, nuts2Id) && region.risk_score > bestScore) {
        bestScore = region.risk_score;
        bestId = nuts3Id;
      }
    }
    return bestId;
  }

  /** Update map with new impact data */
  update(regions: RegionImpact[]): void {
    this.regionData.clear();
    regions.forEach(r => this.regionData.set(r.nuts_id, r));
    // Build NUTS-2 aggregation for GeoJSON coloring
    this.nuts2Data = aggregateToNuts2(this.regionData);
    this.render();
  }

  /** Update map with infrastructure for the selected region */
  updateInfrastructure(infra: Infrastructure[]): void {
    this.selectedInfraData = infra;
    this.render();
  }

  /** Auto-display infrastructure for all critical/emergency regions */
  updateCriticalInfrastructure(infraMap: Map<string, Infrastructure[]>): void {
    this.criticalInfraData = infraMap;
    this.render();
  }

  /** Set the currently selected region (for highlight) */
  setSelectedRegion(nutsId: string | null): void {
    this.selectedNutsId = nutsId;
    this.render();
  }

  private render(): void {
    if (!this.deck) return;
    const layers: Layer[] = [];

    // ─── Layer 1: NUTS GeoJSON (Extruded Polygons) ─────────────
    if (this.nutsGeoJson) {
      layers.push(
        new GeoJsonLayer({
          id: 'nuts-regions',
          data: this.nutsGeoJson as any,
          pickable: true,
          stroked: true,
          filled: true,
          extruded: this.is3D,
          wireframe: false,
          getElevation: (d: { properties?: { NUTS_ID?: string } }) => {
            const nuts2Id = d?.properties?.NUTS_ID ?? '';
            const region = this.nuts2Data.get(nuts2Id);
            return region ? region.risk_score * 800 : 0;
          },
          getFillColor: (d: { properties?: { NUTS_ID?: string } }) => {
            const nuts2Id = d?.properties?.NUTS_ID ?? '';
            // Highlight selected region's parent
            if (this.selectedNutsId && isChildOf(this.selectedNutsId, nuts2Id)) {
              const region = this.nuts2Data.get(nuts2Id);
              if (region) {
                const base = riskToColor(region.risk_score);
                return [base[0], base[1], base[2], 255] as [number, number, number, number];
              }
            }
            const region = this.nuts2Data.get(nuts2Id);
            return region ? riskToColor(region.risk_score) : [30, 40, 60, 80] as [number, number, number, number];
          },
          getLineColor: (d: { properties?: { NUTS_ID?: string } }) => {
            const nuts2Id = d?.properties?.NUTS_ID ?? '';
            // Glow border for selected region
            if (this.selectedNutsId && isChildOf(this.selectedNutsId, nuts2Id)) {
              return [100, 180, 255, 255] as [number, number, number, number];
            }
            const region = this.nuts2Data.get(nuts2Id);
            return region ? riskToLineColor(region.risk_score) : [60, 80, 120, 100] as [number, number, number, number];
          },
          getLineWidth: (d: { properties?: { NUTS_ID?: string } }) => {
            const nuts2Id = d?.properties?.NUTS_ID ?? '';
            if (this.selectedNutsId && isChildOf(this.selectedNutsId, nuts2Id)) {
              return 400; // Thicker border for selected
            }
            const region = this.nuts2Data.get(nuts2Id);
            return region ? 200 : 80;
          },
          material: {
            ambient: 0.35,
            diffuse: 0.6,
            shininess: 32,
            specularColor: [60, 130, 246],
          },
          updateTriggers: {
            getElevation: [this.nuts2Data, this.is3D],
            getFillColor: [this.nuts2Data, this.selectedNutsId],
            getLineColor: [this.nuts2Data, this.selectedNutsId],
            getLineWidth: [this.selectedNutsId],
          },
          transitions: {
            getElevation: 600,
            getFillColor: 400,
          },
        }),
      );
    }

    // ─── Layer 2: Region Points (fallback when no GeoJSON) ─────
    const regionPoints = Array.from(this.regionData.values()).map(r => ({
      nuts_id: r.nuts_id,
      name: r.region_name,
      risk_score: r.risk_score,
      hazard_type: r.hazard_type,
      alert_level: r.alert_level,
      affected_population: r.affected_population,
    }));

    if (regionPoints.length > 0 && !this.nutsGeoJson) {
      layers.push(
        new ScatterplotLayer({
          id: 'region-markers',
          data: regionPoints,
          pickable: true,
          stroked: true,
          filled: true,
          radiusMinPixels: 8,
          radiusMaxPixels: 40,
          getPosition: (_d: object) => {
            return [26.0, 46.0, 0];
          },
          getRadius: (d: { risk_score: number }) => d.risk_score * 500,
          getFillColor: (d: { risk_score: number }) => riskToColor(d.risk_score),
          getLineColor: [255, 255, 255, 100],
          getLineWidth: 2,
        }),
      );
    }

    // ─── Layer 3: Critical Infrastructure (Auto-display) ───────
    // Shows infrastructure markers for ALL critical/emergency regions
    const allCriticalInfra: Infrastructure[] = [];
    for (const [, infra] of this.criticalInfraData) {
      allCriticalInfra.push(...infra);
    }

    if (allCriticalInfra.length > 0) {
      // ScatterplotLayer — colored dots for infrastructure
      layers.push(
        new ScatterplotLayer({
          id: 'critical-infra-scatter',
          data: allCriticalInfra,
          pickable: true,
          stroked: true,
          filled: true,
          radiusMinPixels: 4,
          radiusMaxPixels: 16,
          getPosition: (d: Infrastructure) => [d.longitude, d.latitude, this.is3D ? 1200 : 0],
          getRadius: (d: Infrastructure) => infraMarkerRadius(d.type),
          getFillColor: (d: Infrastructure) => infraMarkerColor(d.type),
          getLineColor: [255, 255, 255, 160],
          getLineWidth: 1.5,
          updateTriggers: {
            getPosition: [this.is3D],
          },
        }),
      );
    }

    // ─── Layer 4: Selected Region Infrastructure Icons ─────────
    // Shows detailed emoji icons ONLY for the currently selected region
    if (this.selectedInfraData.length > 0) {
      layers.push(
        new TextLayer({
          id: 'selected-infra-icons',
          data: this.selectedInfraData,
          pickable: true,
          getPosition: (d: Infrastructure) => [d.longitude, d.latitude, this.is3D ? 1800 : 0],
          getText: (d: Infrastructure) => infraIcon(d.type),
          getSize: 32,
          getColor: [255, 255, 255, 255],
          getAngle: 0,
          getTextAnchor: 'middle' as const,
          getAlignmentBaseline: 'center' as const,
          updateTriggers: {
            getPosition: [this.is3D],
          },
        })
      );
    }

    this.deck.setProps({ layers });
  }

  private handleHover(info: any): void {
    const layerId = info.layer?.id;

    // Handle infrastructure hover
    if (layerId === 'critical-infra-scatter' || layerId === 'selected-infra-icons') {
      const infraItem = info.object as Infrastructure | undefined;
      if (infraItem) {
        this.tooltipEl.innerHTML = `
          <div class="tooltip-title">${infraIcon(infraItem.type)} ${infraItem.name}</div>
          <div class="tooltip-row"><span>Type</span><span class="tooltip-val" style="text-transform:capitalize">${infraItem.type.replace('_', ' ')}</span></div>
          <div class="tooltip-row"><span>Region</span><span class="tooltip-val">${infraItem.nuts_id}</span></div>
          <div class="tooltip-row tooltip-warning">⚠️ At risk from active flooding</div>
        `;
        this.tooltipEl.style.left = `${info.x + 14}px`;
        this.tooltipEl.style.top = `${info.y + 14}px`;
        this.tooltipEl.classList.add('visible');
        return;
      }
    }

    // Handle GeoJSON region hover
    const obj = info.object as { properties?: { NUTS_ID?: string; NUTS_NAME?: string; NAME_LATN?: string } } | undefined;
    const nuts2Id = obj?.properties?.NUTS_ID;

    if (nuts2Id && this.nuts2Data.has(nuts2Id)) {
      const region = this.nuts2Data.get(nuts2Id)!;
      const geoName = obj?.properties?.NUTS_NAME || obj?.properties?.NAME_LATN || region.region_name;

      this.tooltipEl.innerHTML = `
        <div class="tooltip-title">${geoName}</div>
        <div class="tooltip-row"><span>Risk Score</span><span class="tooltip-val">${region.risk_score.toFixed(1)}</span></div>
        <div class="tooltip-row"><span>Alert Level</span><span class="tooltip-val" style="text-transform:capitalize">${region.alert_level}</span></div>
        <div class="tooltip-row"><span>Hazard</span><span class="tooltip-val" style="text-transform:capitalize">${region.hazard_type}</span></div>
        <div class="tooltip-row"><span>Affected</span><span class="tooltip-val">${region.affected_population.toLocaleString()}</span></div>
      `;
      this.tooltipEl.style.left = `${info.x + 14}px`;
      this.tooltipEl.style.top = `${info.y + 14}px`;
      this.tooltipEl.classList.add('visible');
    } else {
      this.tooltipEl.classList.remove('visible');
    }
  }

  /** Fly camera to a specific location */
  flyTo(longitude: number, latitude: number, zoom = 8): void {
    if (!this.deck) return;
    this.deck.setProps({
      initialViewState: {
        ...this.viewState,
        longitude,
        latitude,
        zoom,
        pitch: 55,
        transitionDuration: 1500,
      },
    });
  }

  /** Reset to initial EU view */
  resetView(): void {
    if (!this.deck) return;
    this.deck.setProps({ initialViewState: { ...INITIAL_VIEW_STATE, transitionDuration: 1000 } });
  }

  /** Toggle 3D extrusion */
  toggle3D(): boolean {
    this.is3D = !this.is3D;
    this.render();
    return this.is3D;
  }

  /** Zoom in */
  zoomIn(): void {
    this.viewState = { ...this.viewState, zoom: Math.min(this.viewState.zoom + 1, 18), transitionDuration: 300 };
    this.deck?.setProps({ initialViewState: this.viewState });
  }

  /** Zoom out */
  zoomOut(): void {
    this.viewState = { ...this.viewState, zoom: Math.max(this.viewState.zoom - 1, 2), transitionDuration: 300 };
    this.deck?.setProps({ initialViewState: this.viewState });
  }
}
