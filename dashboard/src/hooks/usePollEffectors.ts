'use client';
/**
 * usePollEffectors — polls GET /effectors on a fixed interval and returns
 * the current list of registered effector IDs.
 *
 * @param intervalMs  Poll interval in milliseconds (default 10 000 = 10 s)
 * @returns { effectors: string[], loading: boolean, error: string | null }
 */
import { useCallback, useEffect, useRef, useState } from 'react';

const HUB_URL = process.env.NEXT_PUBLIC_HUB_URL ?? 'http://localhost:8080';

export function usePollEffectors(intervalMs = 10_000) {
  const [effectors, setEffectors] = useState<string[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchEffectors = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${HUB_URL}/effectors`, {
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as string[];
      setEffectors(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      setError((err as Error).message ?? 'hub unreachable');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEffectors();
    const id = setInterval(fetchEffectors, intervalMs);
    return () => {
      clearInterval(id);
      abortRef.current?.abort();
    };
  }, [fetchEffectors, intervalMs]);

  return { effectors, loading, error };
}
