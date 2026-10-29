import { useEffect, useMemo, useState } from 'react';
import type { Champion, FeedbackDraft, FeedbackKind, ModelList, Prediction } from '../types';
import { ChampionIcon } from './ChampionIcon';
import { ACTION, FEEDBACK_KIND, PHASE, SIDE, defaultExpect, percent } from '../labels';

interface Props {
  prediction: Prediction | null; loading: boolean; error: string | null;
  models: ModelList; version: string; onVersion: (version: string) => void;
  champions: Record<string, Champion>; championList: Champion[];
  inBranch: boolean; busy: boolean; onChoose: (champion: string) => void;
  onFeedback: (draft: FeedbackDraft) => Promise<number>;
}

export function PredictionPanel({ prediction, loading, error, models, version, onVersion, champions, championList, inBranch, busy, onChoose, onFeedback }: Props) {
  const [open, setOpen] = useState<string | null>(null);
  const [form, setForm] = useState<{ kind: FeedbackKind; champion: string | null } | null>(null);
  const [saved, setSaved] = useState<number | null>(null);
  useEffect(() => { setOpen(null); setForm(null); setSaved(null); }, [prediction]);

  const recorded = new Set([prediction?.actual?.champion, prediction?.paired_actual?.champion].filter(Boolean));
  const reliability = prediction?.reliability;
  const name = (id: string) => champions[id]?.name_zh ?? id;

  return (
    <div className="panel prediction">
      <div className="panel-head">
        <h3>下一手预测</h3>
        <select value={version} onChange={(e) => onVersion(e.target.value)} aria-label="模型版本">
          {models.versions.filter((v) => v.ready).map((v) => (
            <option key={v.version} value={v.version} title={v.description}>
              {v.version}{v.validation ? ` · 验证集 Top-5 ${percent(v.validation.top5)}` : ''}
            </option>
          ))}
        </select>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {!prediction && !error && <p className="muted">{loading ? '计算中…' : 'BP 已完成，没有下一手可预测。'}</p>}
      {prediction && (
        <>
          <p className="prediction-slot">
            第 {prediction.slot.step} 步 · <strong>{prediction.slot.team}</strong>（{SIDE[prediction.slot.side]}）{ACTION[prediction.slot.action]}
            <span className="muted"> · {PHASE[prediction.slot.phase]} · {prediction.candidate_count} 个合法候选{loading ? ' · 更新中…' : ''}</span>
          </p>
          <p className="muted small">
            {reliability && 'top1' in reliability && reliability.top1 !== undefined
              ? `该阶段验证集命中：Top-1 ${percent(reliability.top1)} · Top-5 ${percent(reliability.top5)}（${reliability.decisions} 手）。`
              : reliability?.stale ? '验证报告与当前模型文件不一致，请重新评估。' : '该版本还没有验证报告。'}
            概率是模型对“下一手选谁”的估计，不是胜率；统计只用 {prediction.cutoff} 之前的比赛。
          </p>
          {prediction.notes.length > 0 && <ul className="notes">{prediction.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
          <ol className="candidates">
            {prediction.candidates.map((c) => (
              <li key={c.champion} className={recorded.has(c.champion) ? 'recorded' : ''}>
                <button className="candidate" onClick={() => setOpen(open === c.champion ? null : c.champion)} aria-expanded={open === c.champion}>
                  <span className="rank">{c.rank}</span>
                  <ChampionIcon champion={champions[c.champion]} rawId={c.champion} size={32} />
                  <span className="candidate-main">
                    <span className="candidate-name">{name(c.champion)}{recorded.has(c.champion) && <span className="badge ok">实际</span>}</span>
                    <span className="candidate-reason muted small">{c.reasons[0]?.text ?? '各项信号接近平均'}</span>
                  </span>
                  <span className="prob"><span className="bar" style={{ width: `${Math.min(100, c.probability * 250)}%` }} />{percent(c.probability)}</span>
                </button>
                <span className="candidate-actions">
                  {inBranch && <button className="link" disabled={busy} onClick={() => onChoose(c.champion)}>执行</button>}
                  <button className="link" onClick={() => setForm({ kind: 'too_high', champion: c.champion })}>标记</button>
                </span>
                {open === c.champion && c.reasons.length > 1 && (
                  <ul className="reasons">{c.reasons.slice(1).map((r) => <li key={r.feature}>{r.text}</li>)}</ul>
                )}
              </li>
            ))}
          </ol>
          {[prediction.actual, prediction.paired_actual].filter((a) => a && !prediction.candidates.some((c) => c.champion === a.champion)).map((a) => a && (
            <p key={a.step} className="small">
              {a.step === prediction.slot.step ? '实际这一手' : `同队连选的另一手（第 ${a.step} 步）`}：{name(a.champion)}
              {a.rank ? ` · 模型排第 ${a.rank}（${percent(a.probability ?? 0)}）` : ' · 不在合法候选中'}
            </p>
          ))}
          {saved !== null && <p className="saved small">已记录反馈 #{saved}。之后每个新版本都会重新检查这一条。</p>}
          {form ? (
            <FeedbackForm key={`${form.kind}:${form.champion}`} initial={form} prediction={prediction} championList={championList}
              topK={models.feedback_top_k} onCancel={() => setForm(null)}
              onSubmit={async (draft) => { const id = await onFeedback(draft); setForm(null); setSaved(id); }} />
          ) : (
            <div className="row">
              <button className="link" onClick={() => setForm({ kind: 'too_low', champion: null })}>漏掉了某个英雄？</button>
              <button className="link" onClick={() => setForm({ kind: 'other', champion: null })}>整体有问题？</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

interface FormProps {
  initial: { kind: FeedbackKind; champion: string | null }; prediction: Prediction; championList: Champion[]; topK: number;
  onSubmit: (draft: FeedbackDraft) => Promise<void>; onCancel: () => void;
}

function FeedbackForm({ initial, prediction, championList, topK, onSubmit, onCancel }: FormProps) {
  const byId = useMemo(() => Object.fromEntries(championList.map((c) => [c.id, c])), [championList]);
  const [kind, setKind] = useState<FeedbackKind>(initial.kind);
  const [query, setQuery] = useState(initial.champion ? byId[initial.champion]?.name_zh ?? initial.champion : '');
  const [expect, setExpect] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const needle = query.trim().toLowerCase();
  const champion = needle ? championList.find((c) => [c.name_zh, c.name, c.key].some((n) => n.toLowerCase() === needle)) ?? null : null;
  const rank = champion ? prediction.candidates.find((c) => c.champion === champion.id)?.rank ?? null : null;
  const fallback = defaultExpect(kind, rank, topK);

  const submit = async () => {
    if (kind !== 'other' && !champion) { setError('请从列表中选一个英雄'); return; }
    setSending(true); setError(null);
    try { await onSubmit({ kind, champion: champion?.id ?? null, expect_rank: expect ? Number(expect) : null, note }); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setSending(false); }
  };

  return (
    <div className="feedback-form">
      <h4>标记这条预测</h4>
      <div className="kinds" role="radiogroup" aria-label="问题类型">
        {(['too_high', 'too_low', 'other'] as const).map((k) => (
          <label key={k}><input type="radio" name="kind" checked={kind === k} onChange={() => setKind(k)} /> {FEEDBACK_KIND[k]}</label>
        ))}
      </div>
      <label className="field">英雄{kind === 'other' ? '（可选）' : ''}
        <input list="feedback-champions" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="输入中文或英文名" />
        <datalist id="feedback-champions">{championList.map((c) => <option key={c.id} value={c.name_zh}>{c.name}</option>)}</datalist>
      </label>
      {champion && <p className="muted small">当前{rank ? `排第 ${rank}` : '不在前 10（提交时由后端核对名次）'}</p>}
      {kind !== 'other' && (
        <label className="field">{kind === 'too_high' ? '期望排在第几名之后' : '期望进入前几名'}
          <input type="number" min={1} max={50} value={expect} onChange={(e) => setExpect(e.target.value)}
            placeholder={fallback ? `默认 ${fallback}` : '留空按默认规则'} />
        </label>
      )}
      <label className="field">原因（建议写一句）
        <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="例如：对面中单已经锁了，这里不该再给中路英雄" />
      </label>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="row">
        <button onClick={submit} disabled={sending}>提交</button>
        <button onClick={onCancel} disabled={sending}>取消</button>
      </div>
    </div>
  );
}
