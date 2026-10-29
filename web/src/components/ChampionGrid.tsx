import { useMemo, useState } from 'react';
import type { Champion, DraftState, Prediction } from '../types';
import { ChampionIcon } from './ChampionIcon';
import { reasonText } from '../labels';

interface Props {
  champions: Champion[]; state: DraftState; interactive: boolean;
  onChoose: (champion: string | null) => void; busy: boolean; prediction?: Prediction | null;
}

export function ChampionGrid({ champions, state, interactive, onChoose, busy, prediction }: Props) {
  // Model rank badges only when the prediction is for the state on screen.
  const ranks = useMemo(() => (prediction && prediction.slot.step === state.next?.step
    ? Object.fromEntries(prediction.candidates.map((c) => [c.champion, c.rank])) : {}) as Record<string, number>, [prediction, state.next?.step]);
  const [q, setQ] = useState('');
  const [hideBlocked, setHideBlocked] = useState(false);
  const needle = q.trim().toLowerCase();
  const visible = useMemo(() => champions.filter((c) => {
    if (hideBlocked && state.unavailable[c.id]?.reasons.length) return false;
    return !needle || [c.name, c.name_zh, c.key].some((n) => n.toLowerCase().includes(needle));
  }), [champions, needle, hideBlocked, state.unavailable]);
  const blockedCount = Object.values(state.unavailable).filter((r) => r.reasons.length).length;

  return (
    <div className="grid-wrap">
      <div className="grid-controls">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索英雄（中/英文）" aria-label="搜索英雄" />
        <label><input type="checkbox" checked={hideBlocked} onChange={(e) => setHideBlocked(e.target.checked)} /> 隐藏不可选（{blockedCount}）</label>
        {interactive && state.next?.action === 'ban' && (
          <button onClick={() => onChoose(null)} disabled={busy}>空 ban</button>
        )}
        {!interactive && <span className="muted">历史回放只读；创建分支后可点击英雄推演</span>}
      </div>
      <div className="grid">
        {visible.map((c) => {
          const restriction = state.unavailable[c.id];
          const blocked = !!restriction?.reasons.length;
          const warned = !!restriction?.warnings.length;
          const why = restriction ? [...restriction.reasons, ...restriction.warnings].map(reasonText).join('；') : '';
          return (
            <button key={c.id} className={'champ' + (blocked ? ' blocked' : '') + (warned ? ' warned' : '')}
              disabled={!interactive || blocked || busy || state.complete} onClick={() => onChoose(c.id)}
              title={`${c.name_zh}（${c.name}）${why ? ' · ' + why : ''}`}>
              <ChampionIcon champion={c} size={44} dim={blocked} title={`${c.name_zh}${why ? ' · ' + why : ''}`} />
              {ranks[c.id] && <span className="rank-badge" title={`模型预测第 ${ranks[c.id]} 名`}>{ranks[c.id]}</span>}
              <span className="champ-name">{c.name_zh}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
