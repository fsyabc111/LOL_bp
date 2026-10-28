import { useState } from 'react';
import type { Branch, Champion, Step } from '../types';
import { ChampionIcon } from './ChampionIcon';
import { ACTION, SIDE } from '../labels';

interface Props {
  branches: Branch[]; activeId: number | null; currentStep: number; sequence: Step[]; champions: Record<string, Champion>;
  busy: boolean;
  onCreate: (name: string, fearless: string | null) => void;
  onOpen: (id: number) => void; onExit: () => void; onUndo: () => void; onDelete: (id: number) => void;
}

export function BranchPanel({ branches, activeId, currentStep, sequence, champions, busy, onCreate, onOpen, onExit, onUndo, onDelete }: Props) {
  const [name, setName] = useState('');
  const [fearless, setFearless] = useState('');
  const active = branches.find((b) => b.id === activeId) ?? null;
  const original = active ? sequence.slice(active.fork_step) : [];

  return (
    <div className="panel">
      <h3>分支推演</h3>
      {!active && (
        <div className="branch-create">
          <p className="muted small">从当前第 {currentStep} 步之后分叉，原比赛记录不受影响。</p>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={`分支名（默认：第 ${currentStep} 步分支）`} />
          <select value={fearless} onChange={(e) => setFearless(e.target.value)} aria-label="跨局限制">
            <option value="">跨局限制：沿用本局规则</option>
            <option value="picks_both_teams">假设 Fearless</option>
            <option value="none">假设无跨局限制</option>
          </select>
          <button disabled={busy || currentStep >= sequence.length} onClick={() => { onCreate(name, fearless || null); setName(''); }}>
            从第 {currentStep} 步创建分支
          </button>
        </div>
      )}
      {active && (
        <div className="branch-active">
          <div className="row">
            <strong>{active.name}</strong>
            <span className="muted small">分叉于第 {active.fork_step} 步 · 已推演 {active.actions.length} 步</span>
          </div>
          <div className="row">
            <button onClick={onUndo} disabled={busy || !active.actions.length}>撤销一步</button>
            <button onClick={onExit}>返回历史</button>
          </div>
          {original.length > 0 && (
            <>
              <h4>原比赛后续（仅参考）</h4>
              <ol className="original">
                {original.map((s) => (
                  <li key={s.step} className={`step-${s.side.toLowerCase()}`}>
                    <span className="muted small">{s.step}. {SIDE[s.side]}{ACTION[s.action]}</span>
                    <ChampionIcon champion={champions[s.champion ?? '']} rawId={s.champion} size={22} />
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>
      )}
      {branches.length > 0 && (
        <>
          <h4>本局分支（{branches.length}）</h4>
          <ul className="branch-list">
            {branches.map((b) => (
              <li key={b.id} className={b.id === activeId ? 'active' : ''}>
                <button className="link" onClick={() => onOpen(b.id)}>{b.name}</button>
                <span className="muted small">第 {b.fork_step} 步 +{b.actions.length}{b.fearless_override ? ' · 自定 Fearless' : ''}</span>
                <button className="link danger" onClick={() => { if (confirm(`删除分支「${b.name}」？`)) onDelete(b.id); }}>删除</button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
