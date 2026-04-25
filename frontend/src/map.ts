/**
 * FloodSentry — Deck.gl 3D Digital Twin Map
 * Renders NUTS-3 extruded polygons, infrastructure icons, and tooltips.
 */

import type { RegionImpact, Infrastructure } from './api.ts';

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

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

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

// ── Map Class ─────────────────────────────────────────────────
export class FloodSentryMap {
  private deck: Deck | null = null;
  private viewState = { ...INITIAL_VIEW_STATE };
  private is3D = true;
  private nutsGeoJson: object | null = null;
  private regionData: Map<string, RegionImpact> = new Map();
  private onRegionClick: ((nuts_id: string) => void) | null = null;
  private tooltipEl: HTMLElement;
  private loadingEl: HTMLElement;
  private infraData: Infrastructure[] = [];

  constructor(
    private canvasEl: HTMLCanvasElement,
    private containerEl: HTMLElement,
  ) {
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
      onViewStateChange: ({ viewState }: { viewState: typeof INITIAL_VIEW_STATE }) => {
        this.viewState = viewState;
      },
      layers: [],
      getTooltip: () => null, // we handle tooltip manually
      onHover: (info: { object?: object; x: number; y: number }) => {
        this.handleHover(info);
      },
      onClick: (info: { object?: { properties?: { nuts_id?: string } }; layer?: { id: string } }) => {
        if (info.object && info.layer?.id === 'nuts-regions') {
          const nutsId = (info.object as { properties?: { nuts_id?: string } }).properties?.nuts_id;
          if (nutsId && this.onRegionClick) {
            this.onRegionClick(nutsId);
          }
        }
      },
    });

    // Hide loading after deck initializes
    setTimeout(() => {
      this.loadingEl.classList.add('hidden');
    }, 800);
  }

  /** Update map with new impact data */
  update(regions: RegionImpact[]): void {
    this.regionData.clear();
    regions.forEach(r => this.regionData.set(r.nuts_id, r));
    this.render();
  }

  /** Update map with infrastructure for the selected region */
  updateInfrastructure(infra: Infrastructure[]): void {
    this.infraData = infra;
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
          data: this.nutsGeoJson as object,
          pickable: true,
          stroked: true,
          filled: true,
          extruded: this.is3D,
          wireframe: false,
          getElevation: (d: { properties?: { nuts_id?: string } }) => {
            const region = this.regionData.get(d?.properties?.nuts_id ?? '');
            return region ? region.risk_score * 800 : 0;
          },
          getFillColor: (d: { properties?: { nuts_id?: string } }) => {
            const region = this.regionData.get(d?.properties?.nuts_id ?? '');
            return region ? riskToColor(region.risk_score) : [30, 40, 60, 80];
          },
          getLineColor: (d: { properties?: { nuts_id?: string } }) => {
            const region = this.regionData.get(d?.properties?.nuts_id ?? '');
            return region ? riskToLineColor(region.risk_score) : [60, 80, 120, 100];
          },
          getLineWidth: (d: { properties?: { nuts_id?: string } }) => {
            const region = this.regionData.get(d?.properties?.nuts_id ?? '');
            return region ? 200 : 80;
          },
          material: {
            ambient: 0.35,
            diffuse: 0.6,
            shininess: 32,
            specularColor: [60, 130, 246],
          },
          updateTriggers: {
            getElevation: [this.regionData, this.is3D],
            getFillColor: [this.regionData],
            getLineColor: [this.regionData],
          },
          transitions: {
            getElevation: 600,
            getFillColor: 400,
          },
        }),
      );
    }

    // ─── Layer 2: Region Points (fallback + supplementary) ─────
    const regionPoints = Array.from(this.regionData.values()).map(r => ({
      nuts_id: r.nuts_id,
      name: r.region_name,
      risk_score: r.risk_score,
      hazard_type: r.hazard_type,
      alert_level: r.alert_level,
      affected_population: r.affected_population,
    }));

    if (regionPoints.length > 0) {
      // Import locations from the data we have
      // We'll use scatter points as markers if no GeoJSON
      if (!this.nutsGeoJson) {
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
              // These would come from location data; using approximate coords
              return [26.0, 46.0, 0];
            },
            getRadius: (d: { risk_score: number }) => d.risk_score * 500,
            getFillColor: (d: { risk_score: number }) => riskToColor(d.risk_score),
            getLineColor: [255, 255, 255, 100],
            getLineWidth: 2,
          }),
        );
      }
    }

    // ─── Layer 3: Infrastructure Icons ─────────────
    if (this.infraData.length > 0) {
      layers.push(
        new TextLayer({
          id: 'infrastructure-layer',
          data: this.infraData,
          pickable: true,
          getPosition: d => [d.longitude, d.latitude, 500], // Elevated above polygons
          getText: d => infraIcon(d.type),
          getSize: 32,
          getColor: [255, 255, 255, 255],
          getAngle: 0,
          getTextAnchor: 'middle',
          getAlignmentBaseline: 'center',
        })
      );
    }

    this.deck.setProps({ layers });
  }

  private handleHover(info: { object?: object; x: number; y: number }): void {
    const obj = info.object as { properties?: { nuts_id?: string; name?: string } } | undefined;
    const nutsId = obj?.properties?.nuts_id;

    if (nutsId && this.regionData.has(nutsId)) {
      const region = this.regionData.get(nutsId)!;
      this.tooltipEl.innerHTML = `
        <div class="tooltip-title">${region.region_name}</div>
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
