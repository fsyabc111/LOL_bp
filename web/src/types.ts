export type Side = 'Blue' | 'Red';
export type ActionType = 'ban' | 'pick';

export interface Champion { id: string; key: string; name: string; name_zh: string; icon: string }

export interface SeriesGame {
  gameid: string; game_number: number | null; winner_side: Side | null;
  blue: string; red: string; patch: string; has_leaguepedia: boolean;
}
export interface Series {
  series_id: string; league: string; year: string; date: string; teams: string[];
  numbering: string; games: SeriesGame[];
}

export interface Step { step: number; side: Side; action: ActionType; champion: string | null }

export interface RuleField<T> { value: T; status: string; source: string; default?: RuleField<T> }
export interface Rules {
  tournament: string | null;
  template: RuleField<string>;
  fearless: RuleField<string>;
  disabled_champions: RuleField<string[]>;
  candidate_rules: { rule_id: string; applicability_status: string; unknown_fields: string[] }[];
}

export interface SequenceSource {
  type: 'leaguepedia' | 'oe_columns'; locator?: string; revid?: number; note?: string;
  measured_agreement?: number | null; first_selection_from?: string; conflict?: string | null;
}

export interface GameDetail {
  game: { gameid: string; league: string; date: string; year: string; patch: string; game_number: number | null; winner_side: Side | null; series_id: string };
  teams: Record<Side, { name: string; result: number | null }>;
  first_selection_side: Side;
  sequence: Step[];
  sequence_source: SequenceSource;
  rules: Rules;
  series: { series_id: string; position: number; prior_gameids: string[]; consumed: string[]; prior_status: string };
  replay_findings: { step: number; reasons: string[]; warnings?: string[] }[];
}

export interface Restriction { reasons: string[]; warnings: string[] }
export interface DraftState {
  board: Record<Side, { bans: { step: number; champion: string | null }[]; picks: { step: number; champion: string | null }[] }>;
  step: number; complete: boolean;
  next: { step: number; side: Side; action: ActionType } | null;
  actions: Step[];
  unavailable: Record<string, Restriction>;
}

export interface Branch {
  id: number; gameid: string; fork_step: number; name: string; fearless_override: string | null;
  created_at: string; updated_at: string; actions: Step[];
}
export interface BranchPayload { branch: Branch; state: DraftState; rules: Rules }

export interface Meta {
  leagues: string[]; years: string[]; games: number; series: number;
  oe_order_accuracy: { equal_modulo_unordered_groups_rate: number; compared: number } | null;
  champion_catalog_version: string; champion_pool_note: string;
}

export interface Reason { feature: string; contribution: number; text: string }
export interface Candidate { champion: string; rank: number; probability: number; reasons: Reason[] }
export interface Recorded { step: number; champion: string; rank: number | null; probability: number | null }
export interface HitRates { decisions: number; top1: number; top3: number; top5: number; top10: number }

export interface ModelSummary {
  version: string; description: string; sha256: string; kind: 'fitted' | 'fixed'; ready: boolean;
  validation?: HitRates | null; validation_stale?: boolean;
}
export interface ModelList { default: string | null; feedback_top_k: number; versions: ModelSummary[] }

export interface Prediction {
  model: ModelSummary;
  slot: { step: number; side: Side; action: ActionType; phase: string; team: string; opponent: string };
  cutoff: string; patch: string; candidate_count: number; candidates: Candidate[];
  actual: Recorded | null; paired_actual: Recorded | null;
  reliability: (HitRates & { split: string; stale?: undefined }) | { stale: true } | null;
  notes: string[];
}

export type FeedbackKind = 'too_high' | 'too_low' | 'other';
export interface FeedbackDraft { kind: FeedbackKind; champion: string | null; expect_rank: number | null; note: string }
export interface RankedChampion { champion: string; probability: number }
export interface FeedbackRecord {
  id: number; created_at: string; gameid: string; source: 'replay' | 'branch'; branch: { id: number; name: string } | null;
  fearless_override: string | null; actions: Step[]; slot: { step: number; side: Side; action: ActionType; phase: string };
  model: { version: string; sha256: string }; kind: FeedbackKind; champion: string | null;
  rank: number | null; probability: number | null; expect_rank: number | null; top: RankedChampion[]; note: string;
  game: { date: string; league: string; blue: string; red: string; game_number: number | null } | null;
  recheck: { version: string; verdict: string; rank: number | null; probability: number | null; top: RankedChampion[]; model_file_changed: boolean };
  branch_exists: boolean;
}

export interface CompositionLane {
  role: string; blue: string; red: string; expected: number; champion_part: number; matchup_part: number;
  matchup_games: number; matchup_lane_games: number; matchup_blue_wins: number; blue_lane_games: number; red_lane_games: number; enough: boolean;
}
export interface CompositionSide {
  team: string; confidence: number; assignment: { role: string; champion: string }[];
  profile: { champions: number; magic_share?: number; frontline?: number; ranged?: number; tags?: Record<string, number> };
  flags: { tone: 'ok' | 'warn'; kind: string; text: string }[];
  duos: { roles: string[]; champions: string[]; win_delta: number; gold_delta: number; games: number; lane_games: number; enough: boolean }[];
}
export interface Composition {
  cutoff: string; settings_version: string; half_life_days: number; sides: Record<Side, CompositionSide>; lanes: CompositionLane[];
  early_gold_total: number | null; notes: string[]; traits_note: string;
  backtest: { lane_r: number; lane_n: number; win_auc: number; duo_auc: number; reference_auc: number; range: string[] } | null;
}

export interface LaneInfo { role: string; strength: number; games: number; enough: boolean; against?: string; edge?: number; against_games?: number }
export interface RecommendCandidate {
  champion: string; listed_for: 'model' | 'player' | 'deny'; habit: { rank: number; probability: number };
  player?: { role: string; name: string | null; share: number }; lane?: LaneInfo;
  profile?: { frontline: number[]; magic_share: (number | null)[] };
  responses?: { step: number; side: Side; action: ActionType; top: RankedChampion[] } | null; fearless_cost?: boolean;
  deny?: { rank: number; probability: number } | null; opponent_player?: { role: string; name: string | null; share: number };
  threat?: LaneInfo; own_interest?: { rank: number; probability: number } | null;
}
export interface Recommendation {
  model: ModelSummary; slot: Prediction['slot']; cutoff: string; candidates: RecommendCandidate[]; notes: string[];
  evidence: { split: string; range: string[]; games: number; auc: Record<string, number>; labels: Record<string, string> } | null;
}
