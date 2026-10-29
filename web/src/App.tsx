import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, api } from './api';
import type { Branch, Champion, Composition, DraftState, FeedbackDraft, FeedbackRecord, GameDetail, Meta, ModelList, Prediction, Recommendation, Rules } from './types';
import { SeriesBrowser } from './components/SeriesBrowser';
import { DraftBoard } from './components/DraftBoard';
import { Timeline } from './components/Timeline';
import { ChampionGrid } from './components/ChampionGrid';
import { RulesPanel } from './components/RulesPanel';
import { BranchPanel } from './components/BranchPanel';
import { PredictionPanel } from './components/PredictionPanel';
import { FeedbackPanel } from './components/FeedbackPanel';
import { CompositionPanel } from './components/CompositionPanel';
import { RecommendPanel } from './components/RecommendPanel';
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

const MODEL_KEY = 'lolbp.model';
const TAB_KEY = 'lolbp.tab';
type Tab = 'prediction' | 'recommend' | 'composition';
const TABS: { id: Tab; label: string }[] = [{ id: 'prediction', label: '下一手预测' }, { id: 'recommend', label: '候选对比' }, { id: 'composition', label: '阵容评估' }];
function storedTab(): Tab {
  try { const t = localStorage.getItem(TAB_KEY); return TABS.some((x) => x.id === t) ? (t as Tab) : 'prediction'; } catch { return 'prediction'; }
}
function storedModel() {
  try { return localStorage.getItem(MODEL_KEY); } catch { return null; }
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
  const [models, setModels] = useState<ModelList | null>(null);
  const [version, setVersion] = useState('');
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [predicting, setPredicting] = useState(false);
  const [predictionError, setPredictionError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<FeedbackRecord[]>([]);
  const [tab, setTab] = useState<Tab>(storedTab);
  const [composition, setComposition] = useState<Composition | null>(null);
  const [compositionError, setCompositionError] = useState<string | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [recommendationError, setRecommendationError] = useState<string | null>(null);

  const champions = useMemo(() => Object.fromEntries(championList.map((c) => [c.id, c])), [championList]);

  useEffect(() => {
    Promise.all([api.meta(), api.champions()]).then(([m, c]) => { setMeta(m); setChampionList(c); }).catch((e) => setError(describe(e)));
  }, []);
  useEffect(() => {
    api.models().then((m) => {
      setModels(m);
      const ready = m.versions.filter((v) => v.ready).map((v) => v.version);
      setVersion([storedModel(), m.default].find((v): v is string => !!v && ready.includes(v)) ?? ready[0] ?? '');
    }).catch((e) => setPredictionError(describe(e)));
  }, []);
  useEffect(() => writeRoute(route), [route]);

  const chooseTab = (t: Tab) => {
    setTab(t);
    try { localStorage.setItem(TAB_KEY, t); } catch { /* storage unavailable: the choice lasts for this page only */ }
  };

  // ←/→ step through the replay (not while typing or inside a branch).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (!detail || route.branch !== null || e.altKey || e.ctrlKey || e.metaKey) return;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      const total = detail.sequence.length;
      if (e.key === 'ArrowRight') setRoute((r) => ({ ...r, step: Math.min(total, (r.step ?? total) + 1) }));
      else if (e.key === 'ArrowLeft') setRoute((r) => ({ ...r, step: Math.max(0, (r.step ?? total) - 1) }));
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [detail, route.branch]);

  const chooseVersion = (v: string) => {
    setVersion(v);
    try { localStorage.setItem(MODEL_KEY, v); } catch { /* storage unavailable: the choice lasts for this page only */ }
  };
  const refreshFeedback = useCallback(() => (version ? api.feedback(version).then(setFeedback) : Promise.resolve()), [version]);
  useEffect(() => { refreshFeedback().catch((e) => setPredictionError(describe(e))); }, [refreshFeedback]);

  const refreshBranches = useCallback((gameid: string) => api.branches(gameid).then(setBranches), []);

  useEffect(() => {
    if (!route.game) return;
    setError(null);
    api.game(route.game).then((d) => { setDetail(d); return refreshBranches(d.game.gameid); }).catch((e) => setError(describe(e)));
  }, [route.game, refreshBranches]);

  const step = route.step ?? detail?.sequence.length ?? 0;
  useEffect(() => {
    if (!detail || detail.game.gameid !== route.game) return;
    let stale = false;  // ignore responses that arrive after a newer step or branch was requested
    if (route.branch !== null) {
      api.branch(route.branch).then((p) => { if (!stale) { setState(p.state); setBranchRules(p.rules); } })
        .catch((e) => { if (!stale) { setError(describe(e)); setRoute((r) => ({ ...r, branch: null })); } });
    } else {
      setBranchRules(null);
      api.gameState(detail.game.gameid, step).then((s) => { if (!stale) setState(s); }).catch((e) => { if (!stale) setError(describe(e)); });
    }
    return () => { stale = true; };
  }, [detail, route.game, route.branch, step]);

  // Predictions follow the displayed state: a new state object arrives for every step change, branch action or game switch.
  useEffect(() => {
    if (!detail || !state || !version) return;
    if (state.complete) { setPrediction(null); setPredictionError(null); return; }
    let stale = false;
    setPredicting(true); setPredictionError(null);
    // Replay asks for the step of the displayed state itself, so the prediction always matches the board.
    const request = route.branch !== null ? api.branchPredictions(route.branch, version) : api.gamePredictions(detail.game.gameid, state.step, version);
    request.then((p) => { if (!stale) setPrediction(p); })
      .catch((e) => { if (!stale) { setPrediction(null); setPredictionError(describe(e)); } })
      .finally(() => { if (!stale) setPredicting(false); });
    return () => { stale = true; };
  }, [state, version]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Composition follows the displayed state the same way predictions do.
  useEffect(() => {
    if (!detail || !state) return;
    let stale = false;
    setCompositionError(null);
    const request = route.branch !== null ? api.branchComposition(route.branch) : api.gameComposition(detail.game.gameid, state.step);
    request.then((c) => { if (!stale) setComposition(c); })
      .catch((e) => { if (!stale) { setComposition(null); setCompositionError(describe(e)); } });
    return () => { stale = true; };
  }, [state]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!detail || !state || !version) return;
    if (state.complete) { setRecommendation(null); setRecommendationError(null); return; }
    let stale = false;
    setRecommendationError(null);
    const request = route.branch !== null ? api.branchRecommendations(route.branch, version) : api.gameRecommendations(detail.game.gameid, state.step, version);
    request.then((r) => { if (!stale) setRecommendation(r); })
      .catch((e) => { if (!stale) { setRecommendation(null); setRecommendationError(describe(e)); } });
    return () => { stale = true; };
  }, [state, version]);  // eslint-disable-line react-hooks/exhaustive-deps

  const submitFeedback = async (draft: FeedbackDraft) => {
    if (!detail) throw new Error('未载入比赛');
    const where = route.branch !== null ? { branch_id: route.branch } : { step };
    const record = await api.createFeedback({ ...draft, ...where, gameid: detail.game.gameid, version });
    await refreshFeedback();
    return record.id;
  };

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
              <div className="main-column">
                <div className="tabs" role="tablist">
                  {TABS.map((t) => (
                    <button key={t.id} role="tab" aria-selected={tab === t.id} className={'tab' + (tab === t.id ? ' active' : '')} onClick={() => chooseTab(t.id)}>
                      {t.label}
                    </button>
                  ))}
                  <span className="muted small tab-hint">{route.branch === null ? '回放中可用 ←/→ 逐步' : ''}</span>
                </div>
                {tab === 'prediction' && models && version && (
                  <PredictionPanel prediction={prediction} loading={predicting} error={predictionError} models={models} version={version}
                    onVersion={chooseVersion} champions={champions} championList={championList} inBranch={!!activeBranch} busy={busy}
                    onChoose={(c) => activeBranch && run(() => api.addAction(activeBranch.id, c).then(applyBranch))}
                    onFeedback={submitFeedback} />
                )}
                {!version && predictionError && <div className="error" role="alert">预测不可用：{predictionError}</div>}
                {tab === 'recommend' && version && (
                  <RecommendPanel data={recommendation} error={recommendationError} champions={champions} inBranch={!!activeBranch} busy={busy}
                    onChoose={(c) => activeBranch && run(() => api.addAction(activeBranch.id, c).then(applyBranch))} />
                )}
                {tab === 'composition' && <CompositionPanel composition={composition} error={compositionError} champions={champions} />}
                <ChampionGrid champions={championList} state={state} interactive={!!activeBranch} busy={busy} prediction={prediction}
                  onChoose={(c) => activeBranch && run(() => api.addAction(activeBranch.id, c).then(applyBranch))} />
              </div>
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
                {version && (
                  <FeedbackPanel items={feedback} version={version} champions={champions} busy={busy}
                    onOpen={(item) => setRoute({ game: item.gameid, step: item.source === 'replay' ? item.slot.step - 1 : null,
                                                 branch: item.source === 'branch' && item.branch_exists && item.branch ? item.branch.id : null })}
                    onDelete={(id) => run(async () => { await api.deleteFeedback(id); await refreshFeedback(); })} />
                )}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
