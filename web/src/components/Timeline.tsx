import type { Champion, Step } from '../types';
import { ChampionIcon } from './ChampionIcon';

interface Props {
  sequence: Step[]; step: number; champions: Record<string, Champion>;
  onStep: (step: number) => void; findings: Record<number, string[]>; unorderedGroups: number[][];
}

export function Timeline({ sequence, step, champions, onStep, findings, unorderedGroups }: Props) {
  const grouped = new Set(unorderedGroups.flat());
  return (
    <div className="timeline">
      <div className="timeline-controls">
        <button onClick={() => onStep(0)} disabled={step === 0}>⏮</button>
        <button onClick={() => onStep(Math.max(0, step - 1))} disabled={step === 0}>◀ 上一步</button>
        <span className="muted">{step} / {sequence.length}</span>
        <button onClick={() => onStep(Math.min(sequence.length, step + 1))} disabled={step === sequence.length}>下一步 ▶</button>
        <button onClick={() => onStep(sequence.length)} disabled={step === sequence.length}>⏭</button>
      </div>
      <ol className="steps">
        {sequence.map((s) => (
          <li key={s.step}>
            <button className={`step step-${s.side.toLowerCase()}` + (s.step <= step ? ' done' : '') + (s.step === step ? ' current' : '')}
              onClick={() => onStep(s.step)}
              title={`第 ${s.step} 步${grouped.has(s.step) ? '（同队连选，来源不保证组内先后）' : ''}${findings[s.step] ? ' · ' + findings[s.step].join('；') : ''}`}>
              <span className="step-label">{s.action === 'ban' ? 'B' : 'P'}{s.step}</span>
              <ChampionIcon champion={champions[s.champion ?? '']} rawId={s.champion} size={28} dim={s.action === 'ban'} />
              {findings[s.step] && <span className="step-flag">!</span>}
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
