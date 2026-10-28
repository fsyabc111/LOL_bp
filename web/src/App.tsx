import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, api } from './api';
import type { Branch, Champion, DraftState, GameDetail, Meta, Rules } from './types';
import { SeriesBrowser } from './components/SeriesBrowser';
import { DraftBoard } from './components/DraftBoard';
import { Timeline } from './components/Timeline';
import { ChampionGrid } from './components/ChampionGrid';
import { RulesPanel } from './components/RulesPanel';
import { BranchPanel } from './components/BranchPanel';
import { reasonText } from './labels';

type Route = { game: string | null; step: number | null; branch: number | null };

function readRoute(): Route {
  const p = new URLSearchParams(window.location.hash.slice(1));
  const num = (k: string) => (p.get(k) && !Number.isNaN(Number(p.get(k))) ? Number(p.get(k)) : null);
  return { game: p.get('game'), step: num('step'), branch: num('branch') };
}

function writeRoute(r: Route) {
  const p = new URLSearchParams();
  if (r.game) p.set('game', r.game);
  if (r.branch !== null) p.set('branch', String(r.branch));
  else if (r.step !== null) p.set('step', String(r.step));
  const hash = '#' + p.toString();
  if (window.location.hash !== hash) window.history.replaceState(null, '', hash);
}

function describe(error: unknown) {
  if (error instanceof ApiError) {
    const detail = error.detail as { reasons?: string[] } | string | null;
    if (detail && typeof detail === 'object' && detail.reasons) return '不可执行：' + detail.reasons.map(reasonText).join('；');
    return typeof detail === 'string' ? detail : error.message;
  }
  return String(error);
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [championList, setChampionList] = useState<Champion[]>([]);
  const [route, setRoute] = useState<Route>(readRoute);
  const [detail, setDetail] = useState<GameDetail | null>(null);
  const [state, setState] = useState<DraftState | null>(null);
  const [branchRules, setBranchRules] = useState<Rules | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const champions = useMemo(() => Object.fromEntries(championList.map((c) => [c.id, c])), [championList]);

  useEffect(() => {
    Promise.all([api.meta(), api.champions()]).then(([m, c]) => { setMeta(m); setChampionList(c); }).catch((e) => setError(describe(e)));
  }, []);
  useEffect(() => writeRoute(route), [route]);

  const refreshBranches = useCallback((gameid: string) => api.branches(gameid).then(setBranches), []);

  useEffect(() => {
    if (!route.game) return;
    setError(null);
    api.game(route.game).then((d) => { setDetail(d); return refreshBranches(d.game.gameid); }).catch((e) => setError(describe(e)));
  }, [route.game, refreshBranches]);

  const step = route.step ?? detail?.sequence.length ?? 0;
  useEffect(() => {
    if (!detail || detail.game.gameid !== route.game) return;
    if (route.branch !== null) {
      api.branch(route.branch).then((p) => { setState(p.state); setBranchRules(p.rules); })
        .catch((e) => { setError(describe(e)); setRoute((r) => ({ ...r, branch: null })); });
    } else {
      setBranchRules(null);
      api.gameState(detail.game.gameid, step).then(setState).catch((e) => setError(describe(e)));
    }
  }, [detail, route.game, route.branch, step]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); } catch (e) { setError(describe(e)); } finally { setBusy(false); }
  };

  const applyBranch = (p: { state: DraftState; rules: Rules; branch: Branch }) => {
    setState(p.state); setBranchRules(p.rules);
    setBranches((list) => list.map((b) => (b.id === p.branch.id ? p.branch : b)));
  };

  if (!meta) return <div className="loading">{error ?? '加载中…'}</div>;
  const activeBranch = branches.find((b) => b.id === route.branch) ?? null;
  const findings = Object.fromEntries((detail?.replay_findings ?? []).map((f) => [f.step, [...f.reasons, ...(f.warnings ?? [])].map(reasonText)]));

  return (
    <div className="app">
      <SeriesBrowser meta={meta} selected={route.game} onSelect={(g) => setRoute({ game: g, step: null, branch: null })} />
      <main>
        {!detail && <div className="empty">从左侧选择一局比赛开始复盘。</div>}
        {detail && state && (
          <>
            <header className="game-head">
              <h2>{detail.teams.Blue.name} <span className="muted">vs</span> {detail.teams.Red.name}</h2>
              <span className="muted">{detail.game.date.slice(0, 16)} · {detail.game.league} · 补丁 {detail.game.patch} · 第 {detail.series.position} 局</span>
            </header>
            {error && <div className="error" role="alert">{error}</div>}
            <DraftBoard detail={detail} state={state} champions={champions} branchName={activeBranch?.name} />
            {!activeBranch && (
              <Timeline sequence={detail.sequence} step={step} champions={champions} findings={findings}
                unorderedGroups={detail.sequence_source.type === 'leaguepedia' ? [[8, 9], [10, 11], [18, 19]] : []}
                onStep={(s) => setRoute((r) => ({ ...r, step: s }))} />
            )}
            <div className="workspace">
              <ChampionGrid champions={championList} state={state} interactive={!!activeBranch} busy={busy}
                onChoose={(c) => activeBranch && run(() => api.addAction(activeBranch.id, c).then(applyBranch))} />
              <div className="side-panels">
                <BranchPanel branches={branches} activeId={route.branch} currentStep={step} sequence={detail.sequence}
                  champions={champions} busy={busy}
                  onCreate={(name, fearless) => run(async () => {
                    const p = await api.createBranch({ gameid: detail.game.gameid, fork_step: step, name: name || undefined, fearless_override: fearless });
                    await refreshBranches(detail.game.gameid);
                    setRoute((r) => ({ ...r, branch: p.branch.id }));
                  })}
                  onOpen={(id) => setRoute((r) => ({ ...r, branch: id }))}
                  onExit={() => setRoute((r) => ({ ...r, branch: null, step: activeBranch?.fork_step ?? r.step }))}
                  onUndo={() => activeBranch && run(() => api.undo(activeBranch.id).then(applyBranch))}
                  onDelete={(id) => run(async () => {
                    await api.deleteBranch(id);
                    await refreshBranches(detail.game.gameid);
                    if (route.branch === id) setRoute((r) => ({ ...r, branch: null }));
                  })} />
                <RulesPanel detail={detail} rules={branchRules ?? detail.rules} champions={champions} />
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
