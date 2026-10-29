import { useEffect, useMemo, useRef, useState } from 'react';
import type { Champion, DraftState, Prediction } from '../types';
import { ChampionIcon } from './ChampionIcon';
import { reasonText } from '../labels';

// Short mark on a blocked portrait; the full reason stays in the tooltip.
const MARK: Record<string, string> = { fearless_consumed: 'F', event_disabled: '⊘', not_released: '新', unknown_champion: '?' };

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
  const search = useRef<HTMLInputElement>(null);
  const needle = q.trim().toLowerCase();
  const visible = useMemo(() => champions.filter((c) => {
    if (hideBlocked && state.unavailable[c.id]?.reasons.length) return false;
    return !needle || [c.name, c.name_zh, c.key].some((n) => n.toLowerCase().includes(needle));
  }), [champions, needle, hideBlocked, state.unavailable]);
  const blockedCount = Object.values(state.unavailable).filter((r) => r.reasons.length).length;

  // "/" focuses the search box from anywhere outside a form field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (e.key !== '/' || e.altKey || e.ctrlKey || e.metaKey) return;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      e.preventDefault();
      search.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="grid-wrap">
      <div className="grid-controls">
        <span className="search">
          <input ref={search} value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索英雄（中/英文）" aria-label="搜索英雄"
            onKeyDown={(e) => { if (e.key === 'Escape') { setQ(''); e.currentTarget.blur(); } }} />
          {!q && <kbd>/</kbd>}
        </span>
        <label><input type="checkbox" checked={hideBlocked} onChange={(e) => setHideBlocked(e.target.checked)} /> 隐藏不可选（{blockedCount}）</label>
        {interactive && state.next?.action === 'ban' && (
          <button onClick={() => onChoose(null)} disabled={busy}>空 ban</button>
        )}
        <span className="note">{interactive ? (state.complete ? 'BP 已完成' : '点击英雄执行这一手') : '历史回放只读；创建分支后可点击英雄推演'}</span>
      </div>
      <div className="grid">
        {visible.map((c) => {
          const restriction = state.unavailable[c.id];
          const blocked = !!restriction?.reasons.length;
          const warned = !!restriction?.warnings.length;
          const why = restriction ? [...restriction.reasons, ...restriction.warnings].map(reasonText).join('；') : '';
          const mark = restriction?.reasons.map((r) => MARK[r]).find(Boolean);
          return (
            <button key={c.id} className={'champ' + (blocked ? ' blocked' : '') + (warned ? ' warned' : '')}
              disabled={!interactive || blocked || busy || state.complete} onClick={() => onChoose(c.id)}
              title={`${c.name_zh}（${c.name}）${why ? ' · ' + why : ''}`}>
              <ChampionIcon champion={c} size={48} dim={blocked} title={`${c.name_zh}${why ? ' · ' + why : ''}`} />
              {ranks[c.id] && <span className="rank-badge" title={`模型预测第 ${ranks[c.id]} 名`}>{ranks[c.id]}</span>}
              {mark && <span className="block-mark">{mark}</span>}
              <span className="champ-name">{c.name_zh}</span>
            </button>
          );
        })}
        {!visible.length && <p className="muted small">没有匹配的英雄</p>}
      </div>
    </div>
  );
}
