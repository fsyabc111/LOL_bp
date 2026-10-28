import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Meta, Series } from '../types';

interface Props { meta: Meta; selected: string | null; onSelect: (gameid: string) => void }

export function SeriesBrowser({ meta, selected, onSelect }: Props) {
  const [league, setLeague] = useState('');
  const [year, setYear] = useState(meta.years[meta.years.length - 1] ?? '');
  const [q, setQ] = useState('');
  const [series, setSeries] = useState<Series[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      api.series({ league, year, q }).then(setSeries).catch((e) => setError(String(e)));
    }, 200);
    return () => clearTimeout(timer);
  }, [league, year, q]);

  return (
    <aside className="sidebar">
      <div className="filters">
        <select value={league} onChange={(e) => setLeague(e.target.value)} aria-label="联赛">
          <option value="">全部联赛</option>
          {meta.leagues.map((l) => <option key={l} value={l}>{l === 'WLDs' ? 'WLDs（含资格赛）' : l}</option>)}
        </select>
        <select value={year} onChange={(e) => setYear(e.target.value)} aria-label="年份">
          <option value="">全部年份</option>
          {meta.years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索队伍" aria-label="搜索队伍" />
      </div>
      {error && <p className="error">{error}</p>}
      <ul className="series-list">
        {series.map((s) => (
          <li key={s.series_id} className="series">
            <div className="series-head">
              <span className="muted">{s.date} · {s.league}</span>
              {s.numbering !== 'complete' && <span className="badge warn" title="局序不连续，Fearless 前序局可能不全">局序异常</span>}
            </div>
            <div className="series-teams">{s.teams.join(' vs ')}</div>
            <div className="series-games">
              {s.games.map((g) => (
                <button key={g.gameid} className={'game-chip' + (g.gameid === selected ? ' active' : '')} onClick={() => onSelect(g.gameid)}
                  title={`${g.blue}（蓝）vs ${g.red}（红）· ${g.patch}${g.has_leaguepedia ? ' · 有逐手证据' : ' · OE 列顺序'}`}>
                  G{g.game_number ?? '?'}{g.has_leaguepedia ? '' : '*'}
                </button>
              ))}
            </div>
          </li>
        ))}
        {!series.length && !error && <li className="muted">没有匹配的系列赛</li>}
      </ul>
      <p className="footnote muted">* 无 Leaguepedia 逐手证据，顺序取自 OE 列{meta.oe_order_accuracy ? `（实测一致率 ${(meta.oe_order_accuracy.equal_modulo_unordered_groups_rate * 100).toFixed(2)}%）` : ''}。</p>
    </aside>
  );
}
