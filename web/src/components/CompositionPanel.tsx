import type { Champion, Composition, Side } from '../types';
import { ChampionIcon } from './ChampionIcon';
import { SIDE, percent } from '../labels';

const ROLE: Record<string, string> = { top: '上单', jng: '打野', mid: '中单', bot: '下路', sup: '辅助' };
const SCALE = 600;  // gold at which the lane bar is full

interface Props { composition: Composition | null; error: string | null; champions: Record<string, Champion> }

export function CompositionPanel({ composition, error, champions }: Props) {
  const name = (id: string) => champions[id]?.name_zh ?? id;
  const b = composition?.backtest;
  return (
    <div className="panel composition">
      <h3>阵容评估</h3>
      {error && <div className="error" role="alert">{error}</div>}
      {!composition && !error && <p className="muted">计算中…</p>}
      {composition && (
        <>
          <p className="muted small">
            统计只用 {composition.cutoff} 之前的比赛（半衰期 {composition.half_life_days} 天）。
            {b && ` 回测（${b.range[0]} 至 ${b.range[1]}）：对线期望与实际 15 分钟经济差相关 r=${b.lane_r}，能部分反映对线结果；但前期期望与双人组合都不能区分胜负（AUC ${b.win_auc} / ${b.duo_auc}，0.5 为无信息）。以下是带样本量的描述，不是胜负预测。`}
          </p>
          {composition.notes.length > 0 && <ul className="notes">{composition.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
          {composition.lanes.length === 0
            ? <p className="muted small">双方还没有能对上的位置（分路按英雄历史推断）。</p>
            : (
              <table className="lanes">
                <thead><tr><th>位置</th><th>{SIDE.Blue}</th><th className="center">15 分钟经济期望</th><th>{SIDE.Red}</th><th>样本</th></tr></thead>
                <tbody>
                  {composition.lanes.map((l) => {
                    const width = Math.min(50, (Math.abs(l.expected) / SCALE) * 50);
                    return (
                      <tr key={l.role} className={l.enough ? '' : 'thin'}>
                        <td>{ROLE[l.role]}</td>
                        <td><ChampionIcon champion={champions[l.blue]} rawId={l.blue} size={24} /> {name(l.blue)}</td>
                        <td className="center">
                          <span className="lane-bar" title={`英雄均值 ${l.champion_part >= 0 ? '+' : ''}${l.champion_part}，直接交手修正 ${l.matchup_part >= 0 ? '+' : ''}${l.matchup_part}`}>
                            <span className={l.expected >= 0 ? 'fill blue' : 'fill red'} style={{ width: `${width}%`, [l.expected >= 0 ? 'right' : 'left']: '50%' }} />
                          </span>
                          <span className="small">{l.enough ? `${l.expected >= 0 ? '蓝 +' : '红 +'}${Math.abs(l.expected)}` : '数据不足'}</span>
                        </td>
                        <td><ChampionIcon champion={champions[l.red]} rawId={l.red} size={24} /> {name(l.red)}</td>
                        <td className="muted small" title="直接交手（有 15 分钟数据的局数）· 两个英雄在该位置有 15 分钟数据的局数">
                          交手 {l.matchup_lane_games} · {l.blue_lane_games}/{l.red_lane_games}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          <div className="comp-sides">
            {(['Blue', 'Red'] as Side[]).map((side) => {
              const s = composition.sides[side];
              const p = s.profile;
              return (
                <section key={side} className={`comp-side side-${side.toLowerCase()}`}>
                  <header><strong>{s.team}</strong> <span className="muted small">{SIDE[side]}</span></header>
                  {s.assignment.length > 0 && (
                    <p className="small muted">
                      推断分路：{s.assignment.map((a) => `${ROLE[a.role]} ${name(a.champion)}`).join('、')}
                      {s.confidence < 0.6 && <span className="badge warn">分路存疑</span>}
                    </p>
                  )}
                  {p.champions > 0 && (
                    <p className="chips small">
                      <span className="chip" title={composition.traits_note}>魔法伤害约 {percent(p.magic_share ?? 0)}</span>
                      <span className="chip" title={composition.traits_note}>前排 {p.frontline}</span>
                      <span className="chip" title={composition.traits_note}>远程 {p.ranged}</span>
                    </p>
                  )}
                  {s.flags.length > 0 && <ul className="flags">{s.flags.map((f) => <li key={f.text} className={f.tone}>{f.text}</li>)}</ul>}
                  {s.duos.length > 0 && (
                    <ul className="duos small">
                      {s.duos.map((d) => (
                        <li key={d.roles.join()}>
                          {ROLE[d.roles[0]]}+{ROLE[d.roles[1]]} {name(d.champions[0])}·{name(d.champions[1])}：
                          {d.enough
                            ? ` 同队 ${d.games} 局，胜率比两英雄各自预期 ${d.win_delta >= 0 ? '高' : '低'} ${Math.abs(d.win_delta * 100).toFixed(0)} 个百分点`
                            : ` 同队仅 ${d.games} 局，不下结论`}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
