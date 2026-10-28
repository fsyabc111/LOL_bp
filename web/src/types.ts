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
