import type { Champion, Step } from '../types';
import { ChampionIcon } from './ChampionIcon';
import { PHASE } from '../labels';

const PHASES: [string, number][] = [['ban1', 6], ['pick1', 6], ['ban2', 4], ['pick2', 4]];

interface Props {
  sequence: Step[]; step: number; champions: Record<string, Champion>;
  onStep: (step: number) => void; findings: Record<number, string[]>; unorderedGroups: number[][];
  playing: boolean; onTogglePlay: () => void;
}

export function Timeline({ sequence, step, champions, onStep, findings, unorderedGroups, playing, onTogglePlay }: Props) {
  const grouped = new Set(unorderedGroups.flat());
  const total = sequence.length;
  let start = 0;
  const phases = PHASES.map(([phase, n]) => { const items = sequence.slice(start, start + n); start += n; return { phase, items }; });
  if (start < total) phases.push({ phase: '', items: sequence.slice(start) });
  return (
    <div className="timeline">
      <div className="timeline-controls">
        <button onClick={() => onStep(0)} disabled={step === 0} aria-label="回到开始" title="回到开始（Home）">⏮</button>
        <button onClick={() => onStep(Math.max(0, step - 1))} disabled={step === 0} aria-label="上一步" title="上一步（←）">◀</button>
        <span className="counter">{step} / {total}</span>
        <button onClick={() => onStep(Math.min(total, step + 1))} disabled={step === total} aria-label="下一步" title="下一步（→）">▶</button>
        <button onClick={() => onStep(total)} disabled={step === total} aria-label="跳到最后" title="跳到最后（End）">⏭</button>
        <button className={playing ? 'playing' : ''} onClick={onTogglePlay} title="自动播放（空格）">{playing ? '❚❚ 暂停' : '▶ 播放'}</button>
        <span className="hint muted"><kbd>←</kbd> <kbd>→</kbd> 逐步 · <kbd>空格</kbd> 播放</span>
      </div>
      <div className="phases">
        {phases.map(({ phase, items }) => items.length > 0 && (
          <div key={phase || 'extra'} className="phase">
            <span className="phase-name">{PHASE[phase] ?? ''}</span>
            <ol className="steps">
              {items.map((s) => (
                <li key={s.step} className={grouped.has(s.step) ? 'paired' : ''}>
                  <button className={`step step-${s.side.toLowerCase()}` + (s.step <= step ? ' done' : '') + (s.step === step ? ' current' : '')}
                    onClick={() => onStep(s.step)}
                    title={`第 ${s.step} 步 · ${champions[s.champion ?? '']?.name_zh ?? s.champion ?? '空'}${grouped.has(s.step) ? '（同队连选，来源不保证组内先后）' : ''}${findings[s.step] ? ' · ' + findings[s.step].join('；') : ''}`}>
                    <span className="step-label">{s.action === 'ban' ? 'B' : 'P'}{s.step}</span>
                    <ChampionIcon champion={champions[s.champion ?? '']} rawId={s.champion} size={30} dim={s.action === 'ban'} />
                    {findings[s.step] && <span className="step-flag">!</span>}
                  </button>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </div>
  );
}
