/**
 * FloodSentry — Deck.gl 3D Digital Twin Map
 * Task 6: Full integration — NUTS GeoJSON ↔ predictions ↔ infrastructure.
 *
 * - Renders NUTS-2 extruded polygons colored by aggregated risk
 * - Automatically shows infrastructure markers for critical/emergency regions
 * - Tooltips with risk & hazard detail
 */

import type { RegionImpact, Infrastructure } from './api.ts';


// ── Deck.gl / MapLibre imports ────────────────────────────────
import { Deck, LightingEffect, AmbientLight, DirectionalLight } from '@deck.gl/core';
import { GeoJsonLayer, ScatterplotLayer, TextLayer, BitmapLayer } from '@deck.gl/layers';
import { TileLayer } from '@deck.gl/geo-layers';
import type { Layer } from '@deck.gl/core';

const INITIAL_VIEW_STATE = {
  longitude: 10.0,
  latitude: 49.0,
  zoom: 3.8,
  pitch: 45,
  bearing: 0,
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

// NUTS-2 Aggregation removed — rendering directly at NUTS-3 level using GeoJSON.

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
  // Infrastructure — selected region (detail view)
  private selectedInfraData: Infrastructure[] = [];
  // Infrastructure — all critical regions (auto-display on map)
  private criticalInfraData: Map<string, Infrastructure[]> = new Map();
  private selectedNutsId: string | null = null;

  private canvasEl: HTMLCanvasElement;

  // Task 8: Pulsing animation state for critical infrastructure markers
  private pulsePhase = 0;
  private pulseAnimFrame: number | null = null;

  // Task 8: Lighting effect for 3D model
  private lightingEffect: LightingEffect;

  constructor(
    canvasEl: HTMLCanvasElement,
    _containerEl: HTMLElement,
  ) {
    this.canvasEl = canvasEl;
    this.tooltipEl = document.getElementById('map-tooltip')!;
    this.loadingEl = document.getElementById('map-loading')!;

    // Task 8: Create realistic lighting setup for 3D Digital Twin
    const ambientLight = new AmbientLight({
      color: [255, 255, 255],
      intensity: 1.2,
    });

    const sunLight = new DirectionalLight({
      color: [255, 243, 224],   // Warm sunlight tint
      intensity: 1.8,
      direction: [-3, -9, -1],  // Coming from upper-left
    });

    const fillLight = new DirectionalLight({
      color: [180, 200, 255],   // Cool blue fill
      intensity: 0.6,
      direction: [5, 8, -2],    // Opposing side for depth
    });

    this.lightingEffect = new LightingEffect({
      ambientLight,
      sunLight,
      fillLight,
    });
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
      // Task 8: Apply lighting effects for 3D depth and shadows
      effects: [this.lightingEffect],
      getTooltip: () => null, // we handle tooltip manually
      onHover: (info: any) => {
        this.handleHover(info);
      },
      onClick: (info: any) => {
        this.handleClick(info);
      },
    });

    // Task 8: Start pulsing animation loop for critical markers
    this.startPulseAnimation();

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
      // GeoJSON layer uses NUTS_ID (level 3)
      const nutsId = (info.object as { properties?: { NUTS_ID?: string } }).properties?.NUTS_ID;
      if (nutsId && this.regionData.has(nutsId)) {
        this.onRegionClick(nutsId);
      }
    } else if (layerId === 'critical-infra-scatter' || layerId === 'selected-infra-icons') {
      // Clicking infrastructure — find the parent region
      const infraItem = info.object as unknown as Infrastructure;
      if (infraItem?.nuts_id) {
        this.onRegionClick(infraItem.nuts_id);
      }
    }
  }

  /** Update map with new impact data */
  update(regions: RegionImpact[]): void {
    this.regionData.clear();
    regions.forEach(r => this.regionData.set(r.nuts_id, r));
    // Remove NUTS-2 aggregation because we have NUTS-3 geojson
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

    // ─── Layer 0: Base Map (CartoDB Dark Matter) ───────────────
    layers.push(
      new TileLayer({
        id: 'carto-dark-matter',
        data: 'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
        minZoom: 0,
        maxZoom: 19,
        tileSize: 256,
        renderSubLayers: props => {
          const {
            bbox: {west, south, east, north}
          } = props.tile as any;

          return new BitmapLayer({
            ...props,
            data: undefined as any,
            image: props.data as string,
            bounds: [west, south, east, north]
          });
        }
      })
    );

    // ─── Layer 1: NUTS GeoJSON (Extruded Polygons) ─────────────
    if (this.nutsGeoJson) {
      layers.push(
        new GeoJsonLayer({
          id: 'nuts-regions',
          data: this.nutsGeoJson as any,
          pickable: true,
          stroked: true,
          filled: true,
          extruded: true,
          wireframe: false,
          getElevation: (d: { properties?: { NUTS_ID?: string } }) => {
            if (!this.is3D) return 0;
            const nutsId = d?.properties?.NUTS_ID ?? '';
            const region = this.regionData.get(nutsId);
            return region ? region.risk_score * 800 : 0;
          },
          getFillColor: (d: { properties?: { NUTS_ID?: string } }) => {
            const nutsId = d?.properties?.NUTS_ID ?? '';
            // Highlight selected region
            if (this.selectedNutsId && this.selectedNutsId === nutsId) {
              const region = this.regionData.get(nutsId);
              if (region) {
                const base = riskToColor(region.risk_score);
                return [base[0], base[1], base[2], 255] as [number, number, number, number];
              }
            }
            const region = this.regionData.get(nutsId);
            return region ? riskToColor(region.risk_score) : [30, 40, 60, 40] as [number, number, number, number];
          },
          getLineColor: (d: { properties?: { NUTS_ID?: string } }) => {
            const nutsId = d?.properties?.NUTS_ID ?? '';
            // Glow border for selected region
            if (this.selectedNutsId && this.selectedNutsId === nutsId) {
              return [100, 180, 255, 255] as [number, number, number, number];
            }
            const region = this.regionData.get(nutsId);
            return region ? riskToLineColor(region.risk_score) : [60, 80, 120, 80] as [number, number, number, number];
          },
          getLineWidth: (d: { properties?: { NUTS_ID?: string } }) => {
            const nutsId = d?.properties?.NUTS_ID ?? '';
            if (this.selectedNutsId && this.selectedNutsId === nutsId) {
              return 400; // Thicker border for selected
            }
            const region = this.regionData.get(nutsId);
            return region ? 200 : 80;
          },
          // Task 8: Enhanced material properties for realistic lighting
          material: {
            ambient: 0.3,
            diffuse: 0.7,
            shininess: 48,
            specularColor: [80, 160, 255],
          },
          updateTriggers: {
            getElevation: [this.regionData, this.is3D],
            getFillColor: [this.regionData, this.selectedNutsId],
            getLineColor: [this.regionData, this.selectedNutsId],
            getLineWidth: [this.selectedNutsId],
          },
          // Task 8: Smooth elevation transitions when scores change
          transitions: {
            getElevation: { duration: 1200, easing: (t: number) => 1 - Math.pow(1 - t, 3) },
            getFillColor: { duration: 600, easing: (t: number) => t },
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

    // Task 8: Compute pulsing scale for critical markers
    const pulseScale = 1.0 + 0.25 * Math.sin(this.pulsePhase);

    // Determine which infrastructure types should pulse (hospital/school at critical risk)
    const criticalNutsIds = new Set<string>();
    for (const [nutsId] of this.criticalInfraData) {
      criticalNutsIds.add(nutsId);
    }

    if (allCriticalInfra.length > 0) {
      // Task 8: Outer pulse ring for critical hospitals/schools — pulsing glow
      const pulsingItems = allCriticalInfra.filter(
        d => d.type === 'hospital' || d.type === 'school'
      );

      if (pulsingItems.length > 0) {
        const pulseOpacity = Math.floor(60 + 40 * Math.sin(this.pulsePhase));
        layers.push(
          new ScatterplotLayer({
            id: 'critical-infra-pulse-ring',
            data: pulsingItems,
            pickable: false,
            stroked: false,
            filled: true,
            radiusMinPixels: 6,
            radiusMaxPixels: 28,
            getPosition: (d: Infrastructure) => [d.longitude, d.latitude, this.is3D ? 1100 : 10],
            getRadius: (d: Infrastructure) => infraMarkerRadius(d.type) * pulseScale * 1.8,
            getFillColor: (d: Infrastructure) => {
              const base = infraMarkerColor(d.type);
              return [base[0], base[1], base[2], pulseOpacity] as [number, number, number, number];
            },
            updateTriggers: {
              getPosition: [this.is3D],
              getRadius: [pulseScale],
              getFillColor: [pulseOpacity],
            },
          }),
        );
      }

      // ScatterplotLayer — solid colored dots for infrastructure
      layers.push(
        new ScatterplotLayer({
          id: 'critical-infra-scatter',
          data: allCriticalInfra,
          pickable: true,
          stroked: true,
          filled: true,
          radiusMinPixels: 4,
          radiusMaxPixels: 16,
          getPosition: (d: Infrastructure) => [d.longitude, d.latitude, this.is3D ? 1200 : 20],
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
          getPosition: (d: Infrastructure) => [d.longitude, d.latitude, this.is3D ? 1800 : 30],
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
    const nutsId = obj?.properties?.NUTS_ID;

    if (nutsId && this.regionData.has(nutsId)) {
      const region = this.regionData.get(nutsId)!;
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
    
    // Smoothly transition pitch and bearing
    this.viewState = {
      ...this.viewState,
      pitch: this.is3D ? 45 : 0,
      bearing: this.is3D ? -10 : 0,
      transitionDuration: 800
    };
    this.deck?.setProps({ initialViewState: this.viewState });
    
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

  // ── Task 8: Pulsing Animation for Critical Infrastructure ─────

  /** Start the continuous pulse animation loop */
  private startPulseAnimation(): void {
    const animate = () => {
      this.pulsePhase += 0.06;
      // Only re-render if we have critical infrastructure to animate
      if (this.criticalInfraData.size > 0) {
        this.render();
      }
      this.pulseAnimFrame = requestAnimationFrame(animate);
    };
    this.pulseAnimFrame = requestAnimationFrame(animate);
  }

  /** Stop the pulse animation (cleanup) */
  stopPulseAnimation(): void {
    if (this.pulseAnimFrame !== null) {
      cancelAnimationFrame(this.pulseAnimFrame);
      this.pulseAnimFrame = null;
    }
  }
}
