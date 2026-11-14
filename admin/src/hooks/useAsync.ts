import { useCallback, useEffect, useRef, useState } from 'react';

interface AsyncState<T> {
  data?: T;
  error?: string;
  loading: boolean;
  reload: () => void;
}

/**
 * Runs `fn` on mount and whenever `key` changes. Results from superseded calls are
 * dropped, so fast filter changes can't show stale data.
 */
export function useAsync<T>(fn: () => Promise<T>, key = ''): AsyncState<T> {
  const [state, setState] = useState<Omit<AsyncState<T>, 'reload'>>({ loading: true });
  const [nonce, setNonce] = useState(0);
  const fnRef = useRef(fn);

  useEffect(() => {
    fnRef.current = fn;
  });

  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true, error: undefined }));
    fnRef.current().then(
      (data) => live && setState({ data, loading: false }),
      (e: Error) => live && setState((s) => ({ ...s, loading: false, error: e.message })),
    );
    return () => {
      live = false;
    };
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload };
}
