import type { Champion, DraftState, GameDetail, Side } from '../types';
import { ChampionIcon } from './ChampionIcon';
import { ACTION, SIDE } from '../labels';

interface Props { detail: GameDetail; state: DraftState; champions: Record<string, Champion>; branchName?: string }

function SideColumn({ side, detail, state, champions, inBranch }: { side: Side; inBranch: boolean } & Omit<Props, 'branchName'>) {
  const team = detail.teams[side];
  const { bans, picks } = state.board[side];
  const next = state.next?.side === side ? state.next : null;
  const won = detail.game.winner_side === side;
  const slots = (items: { step: number; champion: string | null }[], kind: 'ban' | 'pick') =>
    Array.from({ length: 5 }, (_, i) => {
      const item = items[i];
      const active = next?.action === kind && i === items.length;
      return (
        <div key={i} className={`slot slot-${kind}` + (active ? ' slot-active' : '')}>
          {item ? <ChampionIcon champion={champions[item.champion ?? '']} rawId={item.champion} size={kind === 'pick' ? 52 : 36} dim={kind === 'ban'} />
                : <span className="slot-placeholder">{active ? '…' : ''}</span>}
          {kind === 'pick' && item && <span className="slot-name">{champions[item.champion ?? '']?.name_zh ?? item.champion}</span>}
        </div>
      );
    });
  return (
    <section className={`side side-${side.toLowerCase()}`}>
      <header>
        <strong>{team.name}</strong>
        <span className="muted"> {SIDE[side]}</span>
        {detail.first_selection_side === side && <span className="badge">先选</span>}
        {won && <span className="badge ok" title="历史比赛结果">{inBranch ? '原局胜' : '胜'}</span>}
      </header>
      <div className="bans">{slots(bans, 'ban')}</div>
      <div className="picks">{slots(picks, 'pick')}</div>
    </section>
  );
}

export function DraftBoard({ detail, state, champions, branchName }: Props) {
  return (
    <div className="board-wrap">
      <div className="board-status">
        {branchName && <span className="badge warn">分支：{branchName}</span>}
        {state.next ? <span>第 {state.next.step} 步 · {SIDE[state.next.side]}{ACTION[state.next.action]}</span> : <span>BP 完成</span>}
      </div>
      <div className="board">
        <SideColumn side="Blue" detail={detail} state={state} champions={champions} inBranch={!!branchName} />
        <SideColumn side="Red" detail={detail} state={state} champions={champions} inBranch={!!branchName} />
      </div>
    </div>
  );
}
