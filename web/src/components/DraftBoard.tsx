import type { ReactNode } from 'react';
import type { Champion, DraftState, GameDetail, Prediction, Side } from '../types';
import { ChampionIcon, ChampionSplash } from './ChampionIcon';
import { ACTION, PHASE, SIDE } from '../labels';

const ROLES: [string, string][] = [['top', '上'], ['jng', '野'], ['mid', '中'], ['bot', '下'], ['sup', '辅']];
// Phase of each of the 20 template steps, for the centre progress bar.
const PHASES: [string, number][] = [['ban1', 6], ['pick1', 6], ['ban2', 4], ['pick2', 4]];

interface Props {
  detail: GameDetail; state: DraftState; champions: Record<string, Champion>; branchName?: string;
  prediction?: Prediction | null; children?: ReactNode;
}

function phaseOf(step: number) {
  let end = 0;
  for (const [phase, n] of PHASES) { end += n; if (step <= end) return phase; }
  return 'pick2';
}

function SideColumn({ side, detail, state, champions, inBranch, ghosts }: { side: Side; inBranch: boolean; ghosts: string[] } & Pick<Props, 'detail' | 'state' | 'champions'>) {
  const team = detail.teams[side];
  const { bans, picks } = state.board[side];
  const next = state.next?.side === side ? state.next : null;
  const won = detail.game.winner_side === side;
  const sim = detail.game.simulation?.sides[side];
  const players = sim && !sim.generic ? sim.players : null;

  const ban = (i: number) => {
    const item = bans[i];
    const active = next?.action === 'ban' && i === bans.length;
    const cls = 'ban' + (item ? (item.champion ? ' filled' : ' none') : '') + (active ? ' active' : '');
    return (
      <div key={i} className={cls} title={item ? (champions[item.champion ?? '']?.name_zh ?? (item.champion ? item.champion : '空 ban')) : undefined}>
        {item?.champion && <ChampionIcon champion={champions[item.champion]} rawId={item.champion} size={38} />}
      </div>
    );
  };

  return (
    <section className={`stage-side side-${side.toLowerCase()}`}>
      <header className="team-head">
        <span className="team-name" title={team.name}>{sim?.generic ? '未指定队伍' : team.name}</span>
        <span className="team-meta">
          {SIDE[side]}
          {detail.first_selection_side === side && <span className="badge">先选</span>}
          {won && <span className="badge win" title="历史比赛结果">{inBranch ? '原局胜' : '胜'}</span>}
        </span>
      </header>
      {players && <p className="lineup">{ROLES.map(([r, label]) => <span key={r}>{label} <b>{players[r]?.[1] ?? '—'}</b></span>)}</p>}
      <div className="ban-row">
        <div className="ban-group">{[0, 1, 2].map(ban)}</div>
        <div className="ban-group">{[3, 4].map(ban)}</div>
      </div>
      <div className="pick-col">
        {Array.from({ length: 5 }, (_, i) => {
          const item = picks[i];
          const active = next?.action === 'pick' && i === picks.length;
          const champion = item ? champions[item.champion ?? ''] : null;
          return (
            <div key={i} className={'pick' + (item ? ' filled' : ' vacant') + (active ? ' active' : '')}>
              {item && <ChampionSplash key={item.champion} champion={champion} rawId={item.champion} />}
              <div className="pick-info">
                <span className="pick-no">P{i + 1}{item ? ` · 第 ${item.step} 步` : ''}</span>
                <span className="pick-name">{item ? (champion?.name_zh ?? item.champion) : active ? '选择中…' : ''}</span>
              </div>
              {active && ghosts.length > 0 && (
                <div className="pick-ghosts" title="模型预测前 3">
                  <span className="ghost-label">预测</span>
                  {ghosts.map((id) => <ChampionIcon key={id} champion={champions[id]} rawId={id} size={30} />)}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** Broadcast-style draft board; the timeline (if any) is passed as children and docked underneath. */
export function DraftBoard({ detail, state, champions, branchName, prediction, children }: Props) {
  const next = state.next;
  // Ghost candidates only when the prediction is for the slot on screen.
  const ghosts = prediction && next && prediction.slot.step === next.step ? prediction.candidates.slice(0, 3).map((c) => c.champion) : [];
  const current = next ? phaseOf(next.step) : null;
  const doneUntil = next ? PHASES.findIndex(([p]) => p === current) : PHASES.length;
  const winner = detail.game.winner_side;
  return (
    <section className="stage" aria-label="选禁面板">
      <div className="stage-sides">
        <SideColumn side="Blue" detail={detail} state={state} champions={champions} inBranch={!!branchName} ghosts={next?.side === 'Blue' && next.action === 'pick' ? ghosts : []} />
        <div className="stage-center">
          {next ? (
            <>
              <span className="stage-step-label">STEP</span>
              <span className="stage-step">{String(next.step).padStart(2, '0')}<small>/20</small></span>
              <span className={`stage-turn side-${next.side.toLowerCase()}`}>{SIDE[next.side]}{ACTION[next.action]}</span>
              <span className="stage-phase">{PHASE[current ?? ''] ?? ''}</span>
            </>
          ) : (
            <>
              <span className="stage-step-label">DRAFT</span>
              <span className="stage-turn done">BP 完成</span>
              {winner && !detail.game.simulation && <span className="stage-phase">{branchName ? '原局' : ''}{detail.teams[winner].name} 获胜</span>}
            </>
          )}
          <div className="phase-bar" aria-hidden="true">
            {PHASES.map(([p, n], i) => <span key={p} style={{ flex: n }} className={i < doneUntil ? 'done' : i === doneUntil ? 'now' : ''} />)}
          </div>
          {branchName && <span className="badge">分支：{branchName}</span>}
        </div>
        <SideColumn side="Red" detail={detail} state={state} champions={champions} inBranch={!!branchName} ghosts={next?.side === 'Red' && next.action === 'pick' ? ghosts : []} />
      </div>
      {children}
    </section>
  );
}
