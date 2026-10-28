import type { Champion } from '../types';

interface Props { champion?: Champion | null; rawId?: string | null; size?: number; dim?: boolean; title?: string }

export function ChampionIcon({ champion, rawId, size = 40, dim, title }: Props) {
  if (!champion) {
    const label = rawId ? rawId.replace(/^unknown:/, '') : '空';
    return <span className="icon icon-empty" style={{ width: size, height: size }} title={title ?? label}>{rawId ? '?' : ''}</span>;
  }
  return (
    <img className={'icon' + (dim ? ' icon-dim' : '')} src={champion.icon} width={size} height={size}
      alt={champion.name_zh} title={title ?? `${champion.name_zh}（${champion.name}）`} loading="lazy" />
  );
}
