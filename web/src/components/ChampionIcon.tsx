import { useState } from 'react';
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

// Data Dragon's centered splash art is unversioned; it falls back to the square icon when it fails to load.
const SPLASH_URL = 'https://ddragon.leagueoflegends.com/cdn/img/champion/centered/{key}_0.jpg';

export function ChampionSplash({ champion, rawId }: { champion?: Champion | null; rawId?: string | null }) {
  const [failed, setFailed] = useState<string | null>(null);
  if (!champion || failed === champion.id) {
    return <span className="splash-fallback"><ChampionIcon champion={champion} rawId={rawId} size={44} /></span>;
  }
  return <img className="splash" src={SPLASH_URL.replace('{key}', champion.key)} alt={champion.name_zh} onError={() => setFailed(champion.id)} />;
}
