import { useCallback, useEffect, useRef, useState } from 'react';

/** Loads data on mount and exposes reload/refresh for pull-to-refresh and focus reloads. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const callId = useRef(0);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(async (mode: 'load' | 'refresh' | 'silent' = 'load') => {
    const id = ++callId.current;
    if (mode === 'load') setLoading(true);
    if (mode === 'refresh') setRefreshing(true);
    try {
      const result = await fn();
      if (id === callId.current) {
        setData(result);
        setError(undefined);
      }
    } catch (e) {
      if (id === callId.current) setError((e as Error).message);
    } finally {
      if (id === callId.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, deps);

  useEffect(() => {
    run('load');
  }, [run]);

  return {
    data,
    error,
    loading,
    refreshing,
    reload: () => run('load'),
    refresh: () => run('refresh'),
    silentReload: () => run('silent'),
  };
}
