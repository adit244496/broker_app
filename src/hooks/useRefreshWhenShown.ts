import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';
import { useLeadsLink } from '@/features/tabs/LeadsLink';
import { useRefreshOnFocus } from './useRefreshOnFocus';

/**
 * Re-runs `refetch` whenever this home tab is shown again: on switching to it, when the app comes back to the
 * foreground while it's the current tab, and when the home screen regains focus (e.g. after a lead's details).
 * The tabs are pages of one screen, so screen focus alone misses the first two, and the broker would keep seeing
 * statuses from when the app was opened until they pulled to refresh.
 */
export function useRefreshWhenShown(refetch: () => unknown, tabKey: string) {
  const { activeTab } = useLeadsLink();
  const latest = useRef(refetch);
  const shown = useRef(activeTab === tabKey);

  useEffect(() => {
    latest.current = refetch;
  }, [refetch]);

  useEffect(() => {
    const isShown = activeTab === tabKey;
    if (isShown && !shown.current) latest.current();
    shown.current = isShown;
  }, [activeTab, tabKey]);

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active' && shown.current) latest.current();
    });
    return () => sub.remove();
  }, []);

  useRefreshOnFocus(refetch);
}
