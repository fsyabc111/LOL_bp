import { useState } from 'react';
import type { Champion, LaneInfo, Recommendation, RecommendCandidate } from '../types';
import { ChampionIcon } from './ChampionIcon';
import { Skeleton } from './Toast';
import { ACTION, PHASE, SIDE, percent } from '../labels';

const ROLE: Record<string, string> = { top: '上单', jng: '打野', mid: '中单', bot: '下路', sup: '辅助' };
const LISTED: Record<string, string> = { model: '常见选择', player: '选手拿手', deny: '对手最想要' };

interface Props {
  data: Recommendation | null; error: string | null; champions: Record<string, Champion>;
  inBranch: boolean; busy: boolean; complete: boolean; onChoose: (champion: string) => void;
}

function lane(info: LaneInfo | undefined, name: (id: string) => string, prefix = '') {
  if (!info) return null;
  if (!info.enough) return <span className="chip muted" title={`有 15 分钟数据：${info.games} 局`}>{prefix}{ROLE[info.role]}对线：数据不足</span>;
  const text = info.against !== undefined
    ? `${prefix}对 ${name(info.against)} ${(info.edge ?? 0) >= 0 ? '+' : ''}${info.edge}`
    : `${prefix}${ROLE[info.role]}对线均值 ${info.strength >= 0 ? '+' : ''}${info.strength}`;
  return <span className="chip" title={`15 分钟经济；该英雄样本 ${info.games} 局${info.against_games ? `，对手英雄 ${info.against_games} 局` : ''}`}>{text}</span>;
}

function profileChange(c: RecommendCandidate) {
  if (!c.profile) return null;
  const [f0, f1] = c.profile.frontline; const [m0, m1] = c.profile.magic_share;
  const parts = [];
  if (f1 > f0) parts.push(`前排 ${f0}→${f1}`);
  if (m0 !== null && m1 !== null && Math.abs(m1 - m0) >= 0.05) parts.push(`魔法占比 ${percent(m0)}→${percent(m1)}`);
  return parts.length ? <span className="chip">{parts.join('，')}</span> : null;
}

export function RecommendPanel({ data, error, champions, inBranch, busy, complete, onChoose }: Props) {
  const [open, setOpen] = useState<string | null>(null);
  const name = (id: string) => champions[id]?.name_zh ?? id;
  const evidence = data?.evidence;
  return (
    <div className="panel recommend">
      {error && <div className="error" role="alert">{error}</div>}
      {!data && !error && (complete ? <p className="muted">BP 已完成，没有候选可对比。</p> : <Skeleton rows={4} />)}
      {data && (
        <>
          <div className="slot-line">
            <span className={`side-dot ${data.slot.side === 'Blue' ? 'blue' : 'red'}`} />
            <span>为 <strong>{data.slot.team}</strong>{data.slot.team !== SIDE[data.slot.side] && `（${SIDE[data.slot.side]}）`}{ACTION[data.slot.action]}</span>
            <span className="badge">{PHASE[data.slot.phase]}</span>
          </div>
          <p className="fineprint">
            每个候选并排列出几个角度，供你判断，不给单一的“最优”分数。
            {evidence && ` 回测（${evidence.range[0]} 至 ${evidence.range[1]}，${evidence.games} 局）显示这些角度都不能单独区分胜负：` +
              Object.entries(evidence.auc).map(([k, v]) => `${evidence.labels[k] ?? k} ${v}`).join('，') + '（AUC，0.5 为无信息）。'}
          </p>
          {data.notes.length > 0 && <ul className="notes">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
          <ul className="recs">
            {data.candidates.map((c) => {
              const ours = [
                c.player && <span key="player" className="chip">{c.player.name ?? '未知选手'}（{ROLE[c.player.role]}）近期约 {percent(c.player.share)}</span>,
                c.lane && <span key="lane">{lane(c.lane, name)}</span>,
                profileChange(c) && <span key="profile">{profileChange(c)}</span>,
                c.fearless_cost && <span key="fearless" className="chip muted">Fearless：本系列赛后续不能再选</span>,
              ].filter(Boolean);
              const theirs = [
                c.deny && <span key="deny" className="chip">对手若现在选：第 {c.deny.rank}（{percent(c.deny.probability)}）</span>,
                c.opponent_player && <span key="opp" className="chip">{c.opponent_player.name ?? '未知选手'}（{ROLE[c.opponent_player.role]}）近期约 {percent(c.opponent_player.share)}</span>,
                c.threat && <span key="threat">{lane(c.threat, name, '对手拿到后：')}</span>,
                c.own_interest && c.own_interest.rank <= 10 && <span key="own" className="chip warn">我方也可能想选：第 {c.own_interest.rank}</span>,
              ].filter(Boolean);
              return (
                <li key={c.champion}>
                  <div className="rec-head">
                    <ChampionIcon champion={champions[c.champion]} rawId={c.champion} size={34} />
                    <strong>{name(c.champion)}</strong>
                    <span className={'badge' + (c.listed_for === 'model' ? '' : ' warn')}>{LISTED[c.listed_for]}</span>
                    <span className="muted small">职业常见度 第 {c.habit.rank}（{percent(c.habit.probability)}）</span>
                    <span className="rec-actions">
                      {c.responses && <button className="link" onClick={() => setOpen(open === c.champion ? null : c.champion)}>{open === c.champion ? '收起回应' : '对手回应'}</button>}
                      {inBranch && <button className="link" disabled={busy} onClick={() => onChoose(c.champion)}>执行</button>}
                    </span>
                  </div>
                  {(ours.length > 0 || theirs.length > 0) && (
                    <div className="rec-lines small">
                      {ours.length > 0 && <><span className="who">我方</span><div className="chips">{ours}</div></>}
                      {theirs.length > 0 && <><span className="who them">对手</span><div className="chips">{theirs}</div></>}
                    </div>
                  )}
                  {open === c.champion && c.responses && (
                    <p className="small muted responses">
                      选它之后，第 {c.responses.step} 步{SIDE[c.responses.side]}{ACTION[c.responses.action]}最可能：
                      {c.responses.top.map((r) => `${name(r.champion)} ${percent(r.probability)}`).join('、')}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
