import type { Champion, FeedbackRecord } from '../types';
import { ChampionIcon } from './ChampionIcon';
import { FEEDBACK_KIND, VERDICT } from '../labels';

interface Props {
  items: FeedbackRecord[]; version: string; champions: Record<string, Champion>; busy: boolean;
  onOpen: (item: FeedbackRecord) => void; onDelete: (id: number) => void;
}

function expectation(item: FeedbackRecord) {
  if (item.kind === 'too_high') return `期望排到第 ${item.expect_rank} 名之后`;
  if (item.kind === 'too_low') return `期望进入前 ${item.expect_rank} 名`;
  return '人工复查';
}

export function FeedbackPanel({ items, version, champions, busy, onOpen, onDelete }: Props) {
  const counts = items.reduce<Record<string, number>>((acc, i) => ({ ...acc, [i.recheck.verdict]: (acc[i.recheck.verdict] ?? 0) + 1 }), {});
  return (
    <div>
      {!items.length && <p className="muted small">在预测面板里点“标记”记录不合理的预测。每条都会存下当时的局面，之后每个模型版本都会重新检查。</p>}
      {items.length > 0 && (
        <p className="muted small">
          按 {version} 重新检查：{Object.entries(counts).map(([v, n]) => `${VERDICT[v]?.text ?? v} ${n}`).join('，')}
        </p>
      )}
      <ul className="feedback-list">
        {items.map((item) => {
          const verdict = VERDICT[item.recheck.verdict] ?? { text: item.recheck.verdict, tone: 'muted' as const };
          const openable = item.source === 'replay' || item.branch_exists;
          const champion = item.champion ? champions[item.champion] : null;
          return (
            <li key={item.id}>
              <div className="row small">
                <strong>#{item.id}</strong>
                <span className="muted">
                  {item.game ? `${item.game.date} ${item.game.league} ${item.game.blue} vs ${item.game.red} G${item.game.game_number ?? '?'}` : item.gameid}
                  {' '}· 第 {item.slot.step} 步{item.source === 'branch' ? ` · 分支「${item.branch?.name ?? ''}」` : ''}
                </span>
              </div>
              <div className="row">
                {item.champion && <ChampionIcon champion={champion} rawId={item.champion} size={24} />}
                <span>{champion?.name_zh ?? ''} {FEEDBACK_KIND[item.kind]}</span>
                <span className="muted small">
                  {item.rank ? `${item.model.version} 当时第 ${item.rank} · ` : ''}{expectation(item)}
                </span>
              </div>
              <div className="row">
                <span className={`badge ${verdict.tone}`}>{verdict.text}</span>
                {item.recheck.rank !== null && <span className="small">{item.recheck.version} 现在第 {item.recheck.rank}</span>}
                {item.recheck.model_file_changed && <span className="badge warn" title="记录后该版本的模型文件被改动过">模型文件已改动</span>}
              </div>
              {item.note && <p className="note small">“{item.note}”</p>}
              <div className="row">
                <button className="link" disabled={!openable} onClick={() => onOpen(item)} title={openable ? '' : '分支已删除'}>
                  {openable ? '查看局面' : '分支已删除'}
                </button>
                <button className="link danger" disabled={busy} onClick={() => { if (confirm(`删除反馈 #${item.id}？`)) onDelete(item.id); }}>删除</button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
