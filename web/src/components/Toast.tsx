import { useEffect } from 'react';

interface Props { message: string | null; onClose: () => void }

/** App-level errors; they dismiss themselves after a few seconds. */
export function Toast({ message, onClose }: Props) {
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(onClose, 7000);
    return () => clearTimeout(timer);
  }, [message, onClose]);
  if (!message) return null;
  return (
    <div className="toast-stack">
      <div className="toast" role="alert">
        <span>{message}</span>
        <button className="ghost" onClick={onClose} aria-label="关闭">✕</button>
      </div>
    </div>
  );
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="skeleton" aria-busy="true" aria-label="加载中">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton-row">
          <span className="skeleton-block" style={{ width: 32, height: 32 }} />
          <span className="skeleton-block" style={{ height: 12, width: `${70 - i * 9}%` }} />
        </div>
      ))}
    </div>
  );
}
