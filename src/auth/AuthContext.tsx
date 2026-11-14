import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { sessionStore, setUnauthorizedHandler } from '@/api/client';
import { authApi, profileApi } from '@/api/services';
import type { Session, UserProfile } from '@/types/models';

interface AuthState {
  /** True until the persisted session has been read from secure storage. */
  restoring: boolean;
  session?: Session;
  user?: UserProfile;
  signIn: (session: Session) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [restoring, setRestoring] = useState(true);
  const [session, setSession] = useState<Session>();

  const signOut = useCallback(async () => {
    authApi.logout();
    await sessionStore.clear();
    setSession(undefined);
  }, []);

  const signIn = useCallback(async (next: Session) => {
    await sessionStore.save(next);
    setSession(next);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => void signOut());
    return () => setUnauthorizedHandler(undefined);
  }, [signOut]);

  useEffect(() => {
    (async () => {
      const saved = await sessionStore.load();
      if (saved) {
        authApi.restore(saved);
        setSession(saved);
        // Refresh the cached profile in the background; a 401 here signs the user out.
        profileApi
          .get()
          .then((user) => {
            const updated = { ...saved, user };
            setSession(updated);
            return sessionStore.save(updated);
          })
          .catch(() => {});
      }
      setRestoring(false);
    })();
  }, []);

  const value = useMemo(
    () => ({ restoring, session, user: session?.user, signIn, signOut }),
    [restoring, session, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
