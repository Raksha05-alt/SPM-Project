import { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AuthContext } from "./AuthContext";
import * as authApi from "../api/auth";
import { primeCsrf } from "../api/client";
import type { User } from "../types";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // US-01.1 AC4 - if the session has expired, /me fails and we fall back to
    // the sign-in screen rather than showing a broken page.
    (async () => {
      await primeCsrf().catch(() => undefined);
      try {
        const me = await authApi.fetchMe();
        if (!cancelled) setUser(me);
      } catch {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const me = await authApi.login(email, password);
    await queryClient.cancelQueries();
    queryClient.clear();
    setUser(me);
    return me;
  }, [queryClient]);

  const signOut = useCallback(async () => {
    await authApi.logout();
    await queryClient.cancelQueries();
    queryClient.clear();
    setUser(null);
  }, [queryClient]);

  const value = useMemo(
    () => ({ user, loading, signIn, signOut }),
    [user, loading, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
