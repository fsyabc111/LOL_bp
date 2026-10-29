import { type ReactNode, useEffect, useState } from 'react';

const PANELS_KEY = 'lolbp.panels';

function storedOpen(): Record<string, boolean> {
  try { return JSON.parse(localStorage.getItem(PANELS_KEY) ?? '{}') ?? {}; } catch { return {}; }
}

interface Props { id: string; title: string; badge?: ReactNode; defaultOpen?: boolean; forceOpen?: boolean; children: ReactNode }

/** A collapsible group in the side rail; its open state is remembered per browser. */
export function SidePanel({ id, title, badge, defaultOpen = true, forceOpen, children }: Props) {
  const [open, setOpen] = useState(() => storedOpen()[id] ?? defaultOpen);
  useEffect(() => { if (forceOpen) setOpen(true); }, [forceOpen]);
  const toggle = (next: boolean) => {
    setOpen(next);
    try { localStorage.setItem(PANELS_KEY, JSON.stringify({ ...storedOpen(), [id]: next })); } catch { /* storage unavailable */ }
  };
  return (
    <details className="rail-group" open={open} onToggle={(e) => { const next = (e.currentTarget as HTMLDetailsElement).open; if (next !== open) toggle(next); }}>
      <summary>{title}{badge}</summary>
      {open && <div className="rail-body">{children}</div>}
    </details>
  );
}
