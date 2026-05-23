'use client';
/**
 * AlertToast.tsx
 * Auto-dismissing toast notification for Tier 4/5 threats.
 *
 * Watches the ``threats`` prop and fires a toast whenever a new T4 or T5
 * threat appears (one that was not present in the previous render).
 * Toasts auto-dismiss after 5 s and stack vertically (newest on top).
 */
import { useEffect, useRef, useState } from 'react';
import type { Threat } from '../types';

interface ToastMessage {
  id:      string;
  text:    string;
  tier:    number;
}

interface Props {
  threats: Threat[];
}

const TIER_BORDER: Record<number, string> = {
  4: '#ef4444',
  5: '#be123c',
};

export default function AlertToast({ threats }: Props) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  // Track which threat IDs we have already fired an alert for.
  // Bug fix: remove IDs when a threat disappears so re-appearing threats re-fire.
  const seenRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const currentIds = new Set(threats.map((t) => t.threat_id));

    // Remove IDs that are no longer present — allows re-alerting if a threat
    // disappears and then comes back (e.g. track drop + re-acquire)
    for (const id of seenRef.current) {
      if (!currentIds.has(id)) {
        seenRef.current.delete(id);
      }
    }

    const newToasts: ToastMessage[] = [];
    for (const t of threats) {
      if (t.tier >= 4 && !seenRef.current.has(t.threat_id)) {
        seenRef.current.add(t.threat_id);
        const dist = Math.round(
          Math.sqrt(t.position.x ** 2 + t.position.y ** 2)
        );
        newToasts.push({
          id:   t.threat_id,
          text: `TIER ${t.tier} THREAT — ${dist} m — ${t.drone_type.toUpperCase()}`,
          tier: t.tier,
        });
      }
    }

    if (newToasts.length === 0) return;

    setToasts((prev) => [...newToasts, ...prev].slice(0, 5));   // cap at 5

    // Auto-dismiss after 5 s
    const ids = newToasts.map((m) => m.id);
    const timer = setTimeout(() => {
      setToasts((prev) => prev.filter((m) => !ids.includes(m.id)));
    }, 5000);
    return () => clearTimeout(timer);
  }, [threats]);

  if (toasts.length === 0) return null;

  function dismiss(id: string) {
    setToasts((prev) => prev.filter((m) => m.id !== id));
  }

  return (
    <div
      style={{
        position: 'fixed',
        top: 60,
        right: 16,
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        pointerEvents: 'auto',
      }}
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          style={{
            background: '#0d1117',
            border: `2px solid ${TIER_BORDER[toast.tier] ?? '#ef4444'}`,
            borderRadius: 6,
            padding: '8px 14px',
            minWidth: 260,
            boxShadow: `0 0 16px ${TIER_BORDER[toast.tier] ?? '#ef4444'}55`,
            animation: 'fadeIn 0.2s ease-out',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span
              style={{
                fontSize: 14,
                color: TIER_BORDER[toast.tier] ?? '#ef4444',
                fontWeight: 900,
              }}
            >
              ⚠
            </span>
            <div style={{ flex: 1 }}>
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: 1,
                  color: TIER_BORDER[toast.tier] ?? '#ef4444',
                }}
              >
                CRITICAL THREAT DETECTED
              </div>
              <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
                {toast.text}
              </div>
            </div>
            {/* Manual dismiss button */}
            <button
              onClick={() => dismiss(toast.id)}
              aria-label="Dismiss alert"
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: '#64748b',
                fontSize: 14,
                lineHeight: 1,
                padding: '0 4px',
              }}
            >
              ✕
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
