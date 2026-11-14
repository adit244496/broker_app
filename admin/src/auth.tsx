import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { sessionStore, setUnauthorizedHandler } from '@/api/client';
import { authApi } from '@/api/services';
import type { AdminSession, AdminUser } from '@/types';

interface AuthValue {
  user?: AdminUser;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthValue | undefined>(undefined);

function restore(): AdminSession | undefined {
  const s = sessionStore.load();
  if (s) authApi.restore(s);
  return s;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AdminSession | undefined>(restore);

  const signOut = useCallback(() => {
    authApi.logout(); // sends the token, so before it's cleared
    sessionStore.clear();
    setSession(undefined);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(signOut);
    return () => setUnauthorizedHandler(undefined);
  }, [signOut]);

  const value = useMemo<AuthValue>(
    () => ({
      user: session?.user,
      signIn: async (email, password) => {
        const s = await authApi.login(email, password);
        sessionStore.save(s);
        setSession(s);
      },
      signOut,
    }),
    [session, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
