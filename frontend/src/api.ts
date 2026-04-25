/**
 * FloodSentry API Client
 * Communicates with the FastAPI backend at VITE_API_URL.
 * Task 6: Full frontend↔backend integration with NUTS mapping.
 */

const BASE_URL = (import.meta.env.VITE_API_URL as string) || 'http://localhost:8001';

// ── Types ──────────────────────────────────────────────────────

export interface Location {
  id: number;
  nuts_id: string;
  name: string;
  level: number;
  population: number | null;
  latitude: number;
  longitude: number;
}

export interface Infrastructure {
  id: number;
  nuts_id: string;
  type: string;
  name: string;
  latitude: number;
  longitude: number;
}

export interface Prediction {
  id: number;
  nuts_id: string;
  risk_score: number;
  hazard_type: 'fluvial' | 'pluvial' | 'snowmelt';
  affected_population: number | null;
  rainfall_mm: number | null;
  soil_moisture: number | null;
  ndwi: number | null;
  snow_water_equivalent: number | null;
  river_discharge: number | null;
  temperature_c: number | null;
  predicted_at: string;
  model_version: string | null;
}

export interface InfrastructureAtRisk {
  type: string;
  count: number;
  names: string[];
}

export interface RegionImpact {
  nuts_id: string;
  region_name: string;
  risk_score: number;
  hazard_type: string;
  affected_population: number;
  infrastructure_at_risk: InfrastructureAtRisk[];
  alert_level: 'info' | 'warning' | 'critical' | 'emergency';
  summary_text: string;
}

export interface ImpactSummary {
  total_regions_at_risk: number;
  total_affected_population: number;
  total_hospitals_at_risk: number;
  total_schools_at_risk: number;
  regions: RegionImpact[];
}

export interface AlertRecord {
  id: number;
  nuts_id: string;
  prediction_id: number | null;
  level: 'info' | 'warning' | 'critical' | 'emergency';
  title: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  resolved_at: string | null;
}

export interface SimRegionState {
  nuts_id: string;
  name: string;
  lat: number;
  lon: number;
  risk_score: number;
  alert_level: string;
  wave_active: boolean;
  rainfall_mm: number;
  description: string;
}

export interface SimTimeStep {
  step: number;
  hour: number;
  label: string;
  regions: SimRegionState[];
}

export interface SimulationTimeline {
  scenario: string;
  total_steps: number;
  total_hours: number;
  rainfall_mm: number;
  month: number;
  steps: SimTimeStep[];
  computed_at: string;
}

// ── Hazard Display Helpers ─────────────────────────────────────

/** Human-readable labels for hazard types */
export const HAZARD_LABELS: Record<string, string> = {
  fluvial: 'River Overflow (Fluvial Flooding)',
  pluvial: 'Torrential Rain (Pluvial Flash Floods)',
  snowmelt: 'Snowmelt + Rapid Thaw',
};

/** Detailed flood source descriptions */
export const HAZARD_SOURCES: Record<string, string> = {
  fluvial: 'River overflow from sustained high water levels — river discharge exceeds bank capacity.',
  pluvial: 'Intense localized rainfall exceeding soil absorption — urban flash flood risk.',
  snowmelt: 'Rapid snowmelt (Snowmelt) combined with rising temperatures — runoff surge.',
};

// ── NUTS ID Mapping ────────────────────────────────────────────

/**
 * Derive the NUTS-2 parent from a NUTS-3 ID.
 * E.g., "RO224" → "RO22", "HU333" → "HU33"
 */
export function nutsToLevel2(nutsId: string): string {
  return nutsId.length >= 4 ? nutsId.substring(0, 4) : nutsId;
}

/**
 * Check if a NUTS-3 ID belongs to a NUTS-2 parent.
 */
export function isChildOf(nuts3: string, nuts2: string): boolean {
  return nuts3.startsWith(nuts2);
}

// ── Fetch helpers ──────────────────────────────────────────────

async function get<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(BASE_URL + path);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)));
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

// ── API Methods ────────────────────────────────────────────────

export const api = {
  /** List all NUTS locations */
  getLocations(): Promise<Location[]> {
    return get<Location[]>('/api/v1/locations/');
  },

  /** Get critical infrastructure for a NUTS region */
  getInfrastructure(nutsId: string): Promise<Infrastructure[]> {
    return get<Infrastructure[]>(`/api/v1/locations/${nutsId}/infrastructure`);
  },

  /** Get impact summary across all regions */
  getImpactSummary(minRisk = 30): Promise<ImpactSummary> {
    return get<ImpactSummary>('/api/v1/impact/summary', { min_risk: minRisk });
  },

  /** Get predictions filtered by hazard type */
  getPredictions(nutsId?: string, hazardType?: string): Promise<Prediction[]> {
    const params: Record<string, string | number> = {};
    if (nutsId) params['nuts_id'] = nutsId;
    if (hazardType) params['hazard_type'] = hazardType;
    return get<Prediction[]>('/api/v1/predictions/', params);
  },

  /**
   * Fetch infrastructure for ALL critical/emergency regions in batch.
   * Returns a Map of nuts_id → Infrastructure[].
   */
  async getCriticalInfrastructure(regions: RegionImpact[]): Promise<Map<string, Infrastructure[]>> {
    const critical = regions.filter(
      r => r.alert_level === 'critical' || r.alert_level === 'emergency'
    );
    const results = new Map<string, Infrastructure[]>();
    // Fetch in parallel for all critical regions
    const fetches = critical.map(async r => {
      try {
        const infra = await this.getInfrastructure(r.nuts_id);
        results.set(r.nuts_id, infra);
      } catch {
        results.set(r.nuts_id, []);
      }
    });
    await Promise.all(fetches);
    return results;
  },

  /**
   * Fetch prediction details for a specific region.
   * Enriches the RegionImpact data with sensor readings.
   */
  async getRegionPredictionDetails(nutsId: string): Promise<Prediction | null> {
    try {
      const predictions = await this.getPredictions(nutsId);
      // Return the highest-risk prediction
      return predictions.sort((a, b) => b.risk_score - a.risk_score)[0] ?? null;
    } catch {
      return null;
    }
  },

  // ── Task 7: Alerts ────────────────────────────────────────────

  /** List active alerts */
  getAlerts(nutsId?: string): Promise<AlertRecord[]> {
    const params: Record<string, string | number> = { active_only: 1 };
    if (nutsId) params['nuts_id'] = nutsId;
    return get<AlertRecord[]>('/api/v1/alerts/', params);
  },

  /** Run the alert engine to auto-generate alerts */
  async evaluateAlerts(): Promise<AlertRecord[]> {
    const res = await fetch(BASE_URL + '/api/v1/alerts/evaluate', { method: 'POST' });
    if (!res.ok) throw new Error(`Alert evaluation failed: ${res.status}`);
    return res.json();
  },

  /** Get the download URL for a CAP XML export */
  getCapXmlUrl(alertId: number): string {
    return `${BASE_URL}/api/v1/alerts/${alertId}/export/cap`;
  },

  // ── Task 7: Simulator ────────────────────────────────────────

  /** Fetch the full simulation timeline */
  getSimulationTimeline(rainfallMm = 150, month = 7): Promise<SimulationTimeline> {
    return get<SimulationTimeline>('/api/v1/simulator/timeline', {
      rainfall_mm: rainfallMm,
      month,
    });
  },
};
