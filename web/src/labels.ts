export const REASON: Record<string, string> = {
  already_used_this_game: '本局已选或已禁',
  fearless_consumed: '系列赛前局已选（Fearless）',
  event_disabled: '赛事禁用',
  unknown_champion: '不在英雄目录中',
  empty_pick: '选择不能为空',
  draft_complete: 'BP 已完成',
  template_mismatch: '与选禁模板不符',
  ban_wasted_on_consumed: '禁用的是已消耗英雄，该 ban 无效',
};

export const STATUS: Record<string, { text: string; tone: 'ok' | 'warn' | 'muted' }> = {
  observed: { text: '规则书确认', tone: 'ok' },
  inferred: { text: '规则书推断', tone: 'warn' },
  community_listed: { text: 'Leaguepedia 记录', tone: 'warn' },
  conflicting_sources: { text: '来源冲突', tone: 'warn' },
  practice_observed: { text: '实践观察·规则书未取得', tone: 'warn' },
  assumed: { text: '假设', tone: 'warn' },
  user_assumption: { text: '用户假设', tone: 'warn' },
  unknown: { text: '未知', tone: 'muted' },
};

export const FEARLESS: Record<string, string> = {
  picks_both_teams: '双方前局所选英雄本系列赛不可再选',
  none: '无跨局限制',
};

export const ACTION: Record<string, string> = { ban: '禁用', pick: '选择' };
export const SIDE: Record<string, string> = { Blue: '蓝方', Red: '红方' };

export const reasonText = (code: string) => REASON[code] ?? code;

export const PHASE: Record<string, string> = { ban1: '第一轮禁用', pick1: '第一轮选择', ban2: '第二轮禁用', pick2: '第二轮选择' };
export const FEEDBACK_KIND: Record<string, string> = { too_high: '排太高了', too_low: '应该更靠前', other: '其他问题' };
export const VERDICT: Record<string, { text: string; tone: 'ok' | 'warn' | 'muted' | 'bad' }> = {
  met: { text: '达标', tone: 'ok' },
  improved: { text: '改善但未达标', tone: 'warn' },
  unchanged: { text: '未变', tone: 'muted' },
  worse: { text: '变差', tone: 'bad' },
  review: { text: '待人工复查', tone: 'muted' },
  unavailable: { text: '无法复现', tone: 'muted' },
};

export const percent = (x: number) => (x >= 0.095 ? `${Math.round(x * 100)}%` : `${(x * 100).toFixed(1)}%`);

/** Default expectation, mirroring lolbp/feedback.py: too_high falls below max(K, rank); too_low reaches min(K, rank - 1). */
export function defaultExpect(kind: string, rank: number | null, topK: number) {
  if (rank === null) return null;
  if (kind === 'too_high') return Math.max(topK, rank);
  if (kind === 'too_low') return Math.max(1, Math.min(topK, rank - 1));
  return null;
}
