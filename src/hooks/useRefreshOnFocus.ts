import { useFocusEffect } from 'expo-router';
import { useCallback, useRef } from 'react';

/** Re-runs `refetch` when the screen regains focus (e.g. after closing a create form). Skips the initial focus. */
export function useRefreshOnFocus(refetch: () => unknown) {
  const firstFocus = useRef(true);
  const latest = useRef(refetch);
  latest.current = refetch;

  useFocusEffect(
    useCallback(() => {
      if (firstFocus.current) {
        firstFocus.current = false;
        return;
      }
      latest.current();
    }, []),
  );
}
