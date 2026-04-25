/**
 * FloodSentry API Client
 * Communicates with the FastAPI backend at VITE_API_URL.
 */

const BASE_URL = (import.meta.env.VITE_API_URL as string) || 'http://localhost:8000';

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
};
