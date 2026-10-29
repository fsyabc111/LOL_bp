import { useEffect, useState } from 'react';
import { api } from '../api';
import type { SimPatch, SimTeam, Simulation } from '../types';

const ROLES: [string, string][] = [['top', '上'], ['jng', '野'], ['mid', '中'], ['bot', '下'], ['sup', '辅']];

interface Props {
  selected: string | null; busy: boolean; refresh: number;
  onCreate: (body: { patch: string; blue: string; red: string; league: string }) => void;
  onOpen: (sim: Simulation) => void; onDelete: (sim: Simulation) => void;
}

function Lineup({ team }: { team?: SimTeam }) {
  if (!team) return null;
  return (
    <p className="muted small sim-lineup">
      {ROLES.map(([r, label]) => <span key={r}>{label} {team.players[r]?.[1] ?? '—'}</span>)}
    </p>
  );
}

export function SimulationBrowser({ selected, busy, refresh, onCreate, onOpen, onDelete }: Props) {
  const [patches, setPatches] = useState<SimPatch[]>([]);
  const [patch, setPatch] = useState('');
  const [teams, setTeams] = useState<SimTeam[]>([]);
  const [cutoff, setCutoff] = useState('');
  const [blue, setBlue] = useState('');
  const [red, setRed] = useState('');
  const [leagues, setLeagues] = useState<{ league: string; games: number }[]>([]);
  const [league, setLeague] = useState('');
  const [list, setList] = useState<Simulation[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.simulationPatches().then((p) => { setPatches(p); setPatch((cur) => cur || p[0]?.patch || ''); }).catch((e) => setError(String(e)));
  }, []);
  useEffect(() => { api.simulations().then(setList).catch((e) => setError(String(e))); }, [refresh]);
  useEffect(() => {
    if (!patch) return;
    let stale = false;
    api.simulationTeams(patch).then((t) => {
      if (stale) return;
      setTeams(t.teams); setCutoff(t.cutoff); setLeagues(t.leagues);
      setLeague((l) => (t.leagues.some((x) => x.league === l) ? l : ''));
      // Keep chosen teams that are still listed for the new patch.
      setBlue((b) => (t.teams.some((x) => x.team === b) ? b : ''));
      setRed((r) => (t.teams.some((x) => x.team === r) ? r : ''));
    }).catch((e) => { if (!stale) setError(String(e)); });
    return () => { stale = true; };
  }, [patch]);

  const byId = Object.fromEntries(teams.map((t) => [t.team, t]));
  const onPatch = teams.filter((t) => t.games_on_patch);
  const others = teams.filter((t) => !t.games_on_patch);
  const options = (exclude: string) => (
    <>
      <option value="">不指定队伍（按职业整体习惯）</option>
      <optgroup label="本补丁有比赛">
        {onPatch.filter((t) => t.team !== exclude).map((t) => <option key={t.team} value={t.team}>{t.name} · {t.league} · {t.games_on_patch} 局</option>)}
      </optgroup>
      <optgroup label="近 180 天有比赛">
        {others.filter((t) => t.team !== exclude).map((t) => <option key={t.team} value={t.team}>{t.name} · {t.league} · 最近 {t.last_date}</option>)}
      </optgroup>
    </>
  );

  return (
    <div className="browser">
      <div className="browser-head sim-form">
        <label className="small">补丁
          <select value={patch} onChange={(e) => setPatch(e.target.value)} aria-label="补丁">
            {patches.map((p) => <option key={p.patch} value={p.patch}>{p.patch} · {p.games} 局 · {p.first} ~ {p.last}</option>)}
          </select>
        </label>
        <label className="small">蓝方（先选）
          <select value={blue} onChange={(e) => setBlue(e.target.value)} aria-label="蓝方">{options(red)}</select>
        </label>
        <Lineup team={byId[blue]} />
        <label className="small">红方
          <select value={red} onChange={(e) => setRed(e.target.value)} aria-label="红方">{options(blue)}</select>
        </label>
        <Lineup team={byId[red]} />
        {!blue && (
          <label className="small">规则参照联赛
            <select value={league} onChange={(e) => setLeague(e.target.value)} aria-label="规则参照联赛">
              <option value="">{byId[red] ? `随红方（${byId[red].league}）` : `自动（${leagues[0]?.league ?? '…'}，本补丁比赛最多）`}</option>
              {leagues.map((l) => <option key={l.league} value={l.league}>{l.league} · {l.games} 局</option>)}
            </select>
          </label>
        )}
        <button className="primary" disabled={busy || !patch} onClick={() => onCreate({ patch, blue, red, league: blue ? '' : league })}>开始模拟</button>
        <p className="muted small">
          统计用 {cutoff || '…'} 之前的全部比赛（补丁 {patch} 的最后一场之后）；阵容取各队最近一场的首发。单局模拟，没有系列赛前局。
          不指定队伍的一方只用版本热度和位置分布，不含队伍和选手偏好；选禁规则（含赛事禁用）取自蓝方联赛，蓝方不指定时取上面选的联赛。
        </p>
        {error && <p className="error">{error}</p>}
      </div>
      <ul className="series-list">
        {list.map((s) => (
          <li key={s.id} className={'series' + (s.gameid === selected ? ' active' : '')}>
            <div className="series-head">
              <span className="league">补丁 {s.patch}</span><span>截至 {s.cutoff}</span>
              <button className="link danger" onClick={() => { if (confirm(`删除模拟「${s.name}」？`)) onDelete(s); }}>删除</button>
            </div>
            <button className="link series-teams" onClick={() => onOpen(s)}>{s.sides.Blue.name} vs {s.sides.Red.name}</button>
          </li>
        ))}
        {!list.length && <li className="muted">还没有模拟</li>}
      </ul>
    </div>
  );
}
