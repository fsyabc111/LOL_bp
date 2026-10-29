import type { GameDetail, ModelList } from '../types';
import { percent } from '../labels';

export type Mode = 'replay' | 'sim';
export type Theme = 'auto' | 'light' | 'dark';
const THEME_NEXT: Record<Theme, Theme> = { auto: 'light', light: 'dark', dark: 'auto' };
const THEME_LABEL: Record<Theme, [string, string]> = { auto: ['◐', '跟随系统'], light: ['☀', '浅色'], dark: ['☾', '深色'] };

interface Props {
  mode: Mode; onMode: (mode: Mode) => void;
  sidebarOpen: boolean; onToggleSidebar: () => void;
  theme: Theme; onTheme: (theme: Theme) => void;
  models: ModelList | null; version: string; onVersion: (version: string) => void;
  detail: GameDetail | null;
}

export function TopBar({ mode, onMode, sidebarOpen, onToggleSidebar, theme, onTheme, models, version, onVersion, detail }: Props) {
  const sim = detail?.game.simulation;
  const [icon, label] = THEME_LABEL[theme];
  return (
    <header className="topbar">
      <button className="ghost icon-btn" onClick={onToggleSidebar} aria-label={sidebarOpen ? '收起列表' : '展开列表'} aria-expanded={sidebarOpen} title={sidebarOpen ? '收起列表' : '展开列表'}>☰</button>
      <span className="brand"><span className="brand-mark">BP</span><span className="brand-text">LOL BP 复盘</span></span>
      <div className="segmented" role="tablist" aria-label="模式">
        <button role="tab" aria-selected={mode === 'replay'} onClick={() => onMode('replay')}>比赛复盘</button>
        <button role="tab" aria-selected={mode === 'sim'} onClick={() => onMode('sim')}>模拟 BP</button>
      </div>
      <div className="topbar-summary">
        {detail && (
          <>
            <strong><span className="t-blue">{detail.teams.Blue.name}</span><span className="vs">vs</span><span className="t-red">{detail.teams.Red.name}</span></strong>
            <span className="muted">
              {sim
                ? `模拟 · 补丁 ${sim.patch} · 统计截至 ${sim.cutoff} · 规则参照 ${detail.game.league} 该补丁最后一场 · 单局`
                : `${detail.game.date.slice(0, 16)} · ${detail.game.league} · 补丁 ${detail.game.patch} · 第 ${detail.series.position} 局`}
            </span>
          </>
        )}
      </div>
      <div className="topbar-tools">
        {models && version && (
          <>
            <span className="model-label">模型</span>
            <select value={version} onChange={(e) => onVersion(e.target.value)} aria-label="模型版本">
              {models.versions.filter((v) => v.ready).map((v) => (
                <option key={v.version} value={v.version} title={v.description}>
                  {v.version}{v.validation ? ` · 验证集 Top-5 ${percent(v.validation.top5)}` : ''}
                </option>
              ))}
            </select>
          </>
        )}
        <button className="ghost icon-btn" onClick={() => onTheme(THEME_NEXT[theme])} title={`主题：${label}（点击切换）`} aria-label={`主题：${label}`}>{icon}</button>
      </div>
    </header>
  );
}
