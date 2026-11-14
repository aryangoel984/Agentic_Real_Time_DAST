"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { apiRequest, ApiResult, getToken, setToken } from "./api";

export type CurrentUser = {
  id: number;
  username: string;
  full_name: string;
  role: string;
  agency_id: number;
  agency_name: string;
};

type SessionCtx = {
  user: CurrentUser | null;
  ready: boolean;
  login: (username: string, password: string) => Promise<ApiResult>;
  logout: () => void;
};

const Ctx = createContext<SessionCtx | null>(null);
const USER_KEY = "travelhub_user";

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(USER_KEY);
      if (saved && getToken()) setUser(JSON.parse(saved));
    } catch {
      /* ignore */
    }
    setReady(true);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await apiRequest("POST", "/api/login", { username, password }, { withToken: false });
    if (res.ok) {
      const d = res.data as { token: string; user_id: number };
      setToken(d.token);
      const me = await apiRequest("GET", `/api/users/${d.user_id}`);
      if (me.ok) {
        const u = me.data as CurrentUser;
        setUser(u);
        try {
          localStorage.setItem(USER_KEY, JSON.stringify(u));
        } catch {
          /* ignore */
        }
      }
    }
    return res;
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    try {
      localStorage.removeItem(USER_KEY);
    } catch {
      /* ignore */
    }
    setUser(null);
  }, []);

  return <Ctx.Provider value={{ user, ready, login, logout }}>{children}</Ctx.Provider>;
}

export function useSession(): SessionCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}
