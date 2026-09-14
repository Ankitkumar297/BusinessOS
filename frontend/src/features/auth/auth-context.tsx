import { useCallback, useEffect, useState, type PropsWithChildren } from "react";
import { api, getSession, setSession } from "../../api/client";
import type { AuthSession, User } from "../../types/auth";
import { AuthContext } from "./auth-store";
import { useQueryClient } from "@tanstack/react-query";

export function AuthProvider({ children }: PropsWithChildren): JSX.Element {
  const queryClient = useQueryClient();
  const [session, updateSession] = useState<AuthSession | null>(getSession()); const [isLoading, setLoading] = useState(true);
  useEffect(() => { if (!getSession()) { setLoading(false); return; } api.get<User>("/auth/me").then(({ data }) => { const saved = getSession(); if (saved) { const next = { ...saved, user: data }; setSession(next); updateSession(next); } }).catch(() => { setSession(null); updateSession(null); }).finally(() => setLoading(false)); }, []);
  const persist = useCallback((next: AuthSession) => { queryClient.clear(); setSession(next); updateSession(next); }, [queryClient]);
  const login = async (email: string, password: string): Promise<void> => { const { data } = await api.post<AuthSession>("/auth/login", { email, password }); persist(data); };
  const register = async (businessName: string, fullName: string, email: string, password: string): Promise<void> => { const { data } = await api.post<AuthSession>("/auth/register", { business_name: businessName, full_name: fullName, email, password }); persist(data); };
  const logout = async (): Promise<void> => { try { const current = getSession(); if (current) await api.post("/auth/logout", { refresh_token: current.refresh_token }); } finally { setSession(null); updateSession(null); queryClient.clear(); } };
  const can = (permission: string): boolean => Boolean(session?.user.permissions.includes(permission));
  return <AuthContext.Provider value={{ session, isLoading, login, register, logout, can }}>{children}</AuthContext.Provider>;
}
