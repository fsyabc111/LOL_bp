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
