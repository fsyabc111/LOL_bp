import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, api } from './api';
import type { Branch, Champion, Composition, DraftState, FeedbackDraft, FeedbackRecord, GameDetail, Meta, ModelList, Prediction, Recommendation, Rules } from './types';
import { SeriesBrowser } from './components/SeriesBrowser';
import { SimulationBrowser } from './components/SimulationBrowser';
import { DraftBoard } from './components/DraftBoard';
import { Timeline } from './components/Timeline';
import { ChampionGrid } from './components/ChampionGrid';
import { RulesPanel } from './components/RulesPanel';
import { BranchPanel } from './components/BranchPanel';
import { PredictionPanel } from './components/PredictionPanel';
import { FeedbackPanel } from './components/FeedbackPanel';
import { CompositionPanel } from './components/CompositionPanel';
import { RecommendPanel } from './components/RecommendPanel';
import { type Mode, type Theme, TopBar } from './components/TopBar';
import { SidePanel } from './components/SidePanel';
import { Toast } from './components/Toast';
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
const THEME_KEY = 'lolbp.theme';
const SIDEBAR_KEY = 'lolbp.sidebar';
const NARROW = '(max-width: 760px)';
type Tab = 'prediction' | 'recommend' | 'composition';
const TABS: { id: Tab; label: string }[] = [{ id: 'prediction', label: '下一手预测' }, { id: 'recommend', label: '候选对比' }, { id: 'composition', label: '阵容评估' }];
function storedTab(): Tab {
  try { const t = localStorage.getItem(TAB_KEY); return TABS.some((x) => x.id === t) ? (t as Tab) : 'prediction'; } catch { return 'prediction'; }
}
function storedModel() {
  try { return localStorage.getItem(MODEL_KEY); } catch { return null; }
}
function storedTheme(): Theme {
  try { const t = localStorage.getItem(THEME_KEY); return t === 'light' || t === 'dark' ? t : 'auto'; } catch { return 'auto'; }
}
// The drawer starts open on wide screens; on phones it overlays the page, so it starts closed there.
function initialSidebar() {
  if (window.matchMedia(NARROW).matches) return false;
  try { return localStorage.getItem(SIDEBAR_KEY) !== '0'; } catch { return true; }
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
  const [theme, setTheme] = useState<Theme>(storedTheme);
  const [sidebarOpen, setSidebarOpen] = useState(initialSidebar);
  const [playing, setPlaying] = useState(false);
  const [mode, setMode] = useState<Mode>(() => (readRoute().game?.startsWith('sim-') ? 'sim' : 'replay'));
  const [simRefresh, setSimRefresh] = useState(0);

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

  useEffect(() => {
    if (theme === 'auto') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
  }, [theme]);
  const chooseTheme = (t: Theme) => {
    setTheme(t);
    try { localStorage.setItem(THEME_KEY, t); } catch { /* storage unavailable: the choice lasts for this page only */ }
  };
  const toggleSidebar = () => setSidebarOpen((open) => {
    if (!window.matchMedia(NARROW).matches) {
      try { localStorage.setItem(SIDEBAR_KEY, open ? '0' : '1'); } catch { /* storage unavailable */ }
    }
    return !open;
  });
  // On phones the drawer covers the page, so close it once something is opened from it.
  const closeDrawerIfNarrow = () => { if (window.matchMedia(NARROW).matches) setSidebarOpen(false); };

  const chooseTab = (t: Tab) => {
    setTab(t);
    try { localStorage.setItem(TAB_KEY, t); } catch { /* storage unavailable: the choice lasts for this page only */ }
  };

  // ←/→, Home/End and space step through the replay (not while typing or inside a branch).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (!detail || route.branch !== null || e.altKey || e.ctrlKey || e.metaKey) return;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      if (e.key === ' ' && target && ['BUTTON', 'SUMMARY'].includes(target.tagName)) return;  // space activates the focused control
      const total = detail.sequence.length;
      if (e.key === 'ArrowRight') setRoute((r) => ({ ...r, step: Math.min(total, (r.step ?? total) + 1) }));
      else if (e.key === 'ArrowLeft') setRoute((r) => ({ ...r, step: Math.max(0, (r.step ?? total) - 1) }));
      else if (e.key === 'Home') setRoute((r) => ({ ...r, step: 0 }));
      else if (e.key === 'End') setRoute((r) => ({ ...r, step: total }));
      else if (e.key === ' ') togglePlay();
      else return;
      if (e.key !== ' ') setPlaying(false);
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

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

  // A simulation is always played in its branch (forked at step 0).
  const simulation = detail?.game.simulation ?? null;
  useEffect(() => {
    if (simulation && detail?.game.gameid === route.game && route.branch === null && branches[0]?.gameid === route.game)
      setRoute((r) => ({ ...r, branch: branches[0].id }));
  }, [simulation, detail, branches, route.game, route.branch]);

  const step = route.step ?? detail?.sequence.length ?? 0;
  const total = detail?.sequence.length ?? 0;

  // Autoplay advances one step per second through the replay and stops at the end or on leaving it.
  useEffect(() => { setPlaying(false); }, [route.game, route.branch]);
  useEffect(() => {
    if (!playing) return;
    if (step >= total) { setPlaying(false); return; }
    const timer = setTimeout(() => setRoute((r) => ({ ...r, step: Math.min(total, (r.step ?? total) + 1) })), 1000);
    return () => clearTimeout(timer);
  }, [playing, step, total]);
  function togglePlay() {
    if (playing) { setPlaying(false); return; }
    if (step >= total) setRoute((r) => ({ ...r, step: 0 }));
    setPlaying(true);
  }
  const goStep = (s: number) => { setPlaying(false); setRoute((r) => ({ ...r, step: s })); };
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

  const dismissError = useCallback(() => setError(null), []);
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

  const openSimulation = (gameid: string, branch: number | null) => {
    if (gameid !== route.game) { setDetail(null); setState(null); }
    setRoute({ game: gameid, step: null, branch });
    closeDrawerIfNarrow();
  };
  const choose = (c: string | null) => activeBranch && run(() => api.addAction(activeBranch.id, c).then(applyBranch));
  const shown = detail && state && detail.game.gameid === route.game ? detail : null;

  return (
    <div className={'app' + (sidebarOpen ? '' : ' sidebar-closed')}>
      <TopBar mode={mode} onMode={setMode} sidebarOpen={sidebarOpen} onToggleSidebar={toggleSidebar} theme={theme} onTheme={chooseTheme}
        models={models} version={version} onVersion={chooseVersion} detail={shown} />
      <div className="body">
        <aside className="drawer" aria-hidden={!sidebarOpen}>
          {mode === 'replay'
            ? <SeriesBrowser meta={meta} selected={route.game} onSelect={(g) => { setRoute({ game: g, step: null, branch: null }); closeDrawerIfNarrow(); }} />
            : <SimulationBrowser selected={route.game} busy={busy} refresh={simRefresh}
                onCreate={(body) => run(async () => { const s = await api.createSimulation(body); setSimRefresh((n) => n + 1); openSimulation(s.gameid, s.branch_id ?? null); })}
                onOpen={(s) => openSimulation(s.gameid, s.branch_id ?? null)}
                onDelete={(s) => run(async () => {
                  await api.deleteSimulation(s.id); setSimRefresh((n) => n + 1);
                  if (route.game === s.gameid) { setDetail(null); setState(null); setRoute({ game: null, step: null, branch: null }); }
                })} />}
        </aside>
        <div className="drawer-backdrop" onClick={() => setSidebarOpen(false)} />
        <main>
          {!detail && (
            <div className="empty-state">
              <span className="glyph">{mode === 'sim' ? '⚔' : '▦'}</span>
              <strong>{mode === 'sim' ? '开始一局模拟 BP' : '选择一局比赛开始复盘'}</strong>
              <span>{mode === 'sim' ? '在左侧列表选择补丁和蓝红两支队伍。' : '在左侧列表按联赛、年份或队伍筛选，点局号载入。'}</span>
              {!sidebarOpen && <button className="primary" onClick={toggleSidebar}>打开列表</button>}
            </div>
          )}
          {detail && state && (
            <>
              <DraftBoard detail={detail} state={state} champions={champions} branchName={simulation ? undefined : activeBranch?.name} prediction={prediction}>
                {!activeBranch && (
                  <Timeline sequence={detail.sequence} step={step} champions={champions} findings={findings}
                    unorderedGroups={detail.sequence_source.type === 'leaguepedia' ? [[8, 9], [10, 11], [18, 19]] : []}
                    onStep={goStep} playing={playing} onTogglePlay={togglePlay} />
                )}
              </DraftBoard>
              <div className="workspace">
                <div className="main-column">
                  <div className="analysis">
                    <div className="analysis-head">
                      <div className="segmented" role="tablist" aria-label="分析">
                        {TABS.map((t) => (
                          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => chooseTab(t.id)}>{t.label}</button>
                        ))}
                      </div>
                      <span className="hint">{activeBranch ? (simulation ? '模拟中：点候选“执行”或点英雄格子' : '分支推演中：点候选“执行”或点英雄格子') : ''}</span>
                    </div>
                    {tab === 'prediction' && models && version && (
                      <PredictionPanel prediction={prediction} loading={predicting} error={predictionError} models={models} version={version}
                        champions={champions} championList={championList} inBranch={!!activeBranch} busy={busy}
                        onChoose={choose} onFeedback={submitFeedback} allowFeedback={!simulation} />
                    )}
                    {!version && predictionError && <div className="error" role="alert">预测不可用：{predictionError}</div>}
                    {tab === 'recommend' && version && (
                      <RecommendPanel data={recommendation} error={recommendationError} champions={champions} inBranch={!!activeBranch} busy={busy}
                        complete={state.complete} onChoose={choose} />
                    )}
                    {tab === 'composition' && <CompositionPanel composition={composition} error={compositionError} champions={champions} />}
                  </div>
                  <ChampionGrid champions={championList} state={state} interactive={!!activeBranch} busy={busy} prediction={prediction} onChoose={choose} />
                </div>
                <div className="rail">
                  {simulation && (
                    <SidePanel id="simulation" title="模拟" badge={<span className="badge">已走 {activeBranch?.actions.length ?? 0} 步</span>}>
                      <p className="muted small">在预测、候选对比或英雄格子里点选执行。</p>
                      <div className="row">
                        <button disabled={busy || !activeBranch?.actions.length} onClick={() => activeBranch && run(() => api.undo(activeBranch.id).then(applyBranch))}>撤销一步</button>
                        <button disabled={busy || !activeBranch?.actions.length} onClick={() => activeBranch && run(async () => {
                          const p = await api.createBranch({ gameid: detail.game.gameid, fork_step: 0, name: '模拟' });
                          await api.deleteBranch(activeBranch.id); await refreshBranches(detail.game.gameid);
                          setRoute((r) => ({ ...r, branch: p.branch.id }));
                        })}>重新开始</button>
                      </div>
                      <ul className="muted small lineup-list">
                        {(['Blue', 'Red'] as const).filter((side) => !simulation.sides[side].generic).map((side) => (
                          <li key={side}>{simulation.sides[side].name}：{['top', 'jng', 'mid', 'bot', 'sup'].map((r) => simulation.sides[side].players[r]?.[1] ?? '—').join(' / ')}</li>
                        ))}
                      </ul>
                    </SidePanel>
                  )}
                  {!simulation && (
                    <SidePanel id="branches" title="分支推演" forceOpen={!!activeBranch}
                      badge={activeBranch ? <span className="badge warn">进行中</span> : branches.length ? <span className="badge">{branches.length}</span> : undefined}>
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
                    </SidePanel>
                  )}
                  <SidePanel id="rules" title="规则与证据" defaultOpen={false}
                    badge={detail.replay_findings.length ? <span className="badge warn">{detail.replay_findings.length} 处不一致</span> : undefined}>
                    <RulesPanel detail={detail} rules={branchRules ?? detail.rules} champions={champions} />
                  </SidePanel>
                  {version && (
                    <SidePanel id="feedback" title="反馈记录" defaultOpen={false} badge={<span className="badge">{feedback.length}</span>}>
                      <FeedbackPanel items={feedback} version={version} champions={champions} busy={busy}
                        onOpen={(item) => setRoute({ game: item.gameid, step: item.source === 'replay' ? item.slot.step - 1 : null,
                                                     branch: item.source === 'branch' && item.branch_exists && item.branch ? item.branch.id : null })}
                        onDelete={(id) => run(async () => { await api.deleteFeedback(id); await refreshFeedback(); })} />
                    </SidePanel>
                  )}
                </div>
              </div>
            </>
          )}
        </main>
      </div>
      <Toast message={error} onClose={dismissError} />
    </div>
  );
}
