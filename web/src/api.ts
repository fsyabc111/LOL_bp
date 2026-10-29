import type { BranchPayload, Branch, Champion, Composition, DraftState, FeedbackDraft, FeedbackRecord, GameDetail, Meta, ModelList, Prediction, Recommendation, Series, SimPatch, SimTeam, Simulation } from './types';

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init });
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body?.detail ?? body);
  return body as T;
}

const query = (params: Record<string, string | number | undefined>) => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== '') as [string, string][];
  return entries.length ? '?' + new URLSearchParams(entries).toString() : '';
};

export const api = {
  meta: () => request<Meta>('/api/meta'),
  champions: () => request<Champion[]>('/api/champions'),
  series: (p: { league?: string; year?: string; q?: string }) => request<Series[]>('/api/series' + query(p)),
  game: (id: string) => request<GameDetail>(`/api/games/${encodeURIComponent(id)}`),
  gameState: (id: string, step: number) => request<DraftState>(`/api/games/${encodeURIComponent(id)}/state` + query({ step })),
  branches: (gameid: string) => request<Branch[]>('/api/branches' + query({ gameid })),
  branch: (id: number) => request<BranchPayload>(`/api/branches/${id}`),
  createBranch: (body: { gameid: string; fork_step: number; name?: string; fearless_override?: string | null }) =>
    request<BranchPayload>('/api/branches', { method: 'POST', body: JSON.stringify(body) }),
  addAction: (id: number, champion: string | null) =>
    request<BranchPayload>(`/api/branches/${id}/actions`, { method: 'POST', body: JSON.stringify({ champion }) }),
  undo: (id: number) => request<BranchPayload>(`/api/branches/${id}/undo`, { method: 'POST' }),
  deleteBranch: (id: number) => request<void>(`/api/branches/${id}`, { method: 'DELETE' }),
  simulationPatches: () => request<SimPatch[]>('/api/simulations/patches'),
  simulationTeams: (patch: string) => request<{ patch: string; cutoff: string; teams: SimTeam[]; leagues: { league: string; games: number }[] }>('/api/simulations/teams' + query({ patch })),
  simulations: () => request<Simulation[]>('/api/simulations'),
  createSimulation: (body: { patch: string; blue: string; red: string; league?: string; name?: string }) =>
    request<Simulation>('/api/simulations', { method: 'POST', body: JSON.stringify(body) }),
  deleteSimulation: (id: number) => request<void>(`/api/simulations/${id}`, { method: 'DELETE' }),
  models: () => request<ModelList>('/api/models'),
  gameComposition: (id: string, step: number) => request<Composition>(`/api/games/${encodeURIComponent(id)}/composition` + query({ step })),
  branchComposition: (id: number) => request<Composition>(`/api/branches/${id}/composition`),
  gameRecommendations: (id: string, step: number, version: string) =>
    request<Recommendation | null>(`/api/games/${encodeURIComponent(id)}/recommendations` + query({ step, version })),
  branchRecommendations: (id: number, version: string) => request<Recommendation | null>(`/api/branches/${id}/recommendations` + query({ version })),
  gamePredictions: (id: string, step: number, version: string) =>
    request<Prediction | null>(`/api/games/${encodeURIComponent(id)}/predictions` + query({ step, version })),
  branchPredictions: (id: number, version: string) => request<Prediction | null>(`/api/branches/${id}/predictions` + query({ version })),
  feedback: (version: string) => request<FeedbackRecord[]>('/api/feedback' + query({ version })),
  createFeedback: (body: FeedbackDraft & { gameid: string; step?: number; branch_id?: number; version: string }) =>
    request<FeedbackRecord>('/api/feedback', { method: 'POST', body: JSON.stringify(body) }),
  deleteFeedback: (id: number) => request<void>(`/api/feedback/${id}`, { method: 'DELETE' }),
};
