import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import type { AuthSession } from "../types/auth";

const storageKey = "businessos.session";
export const getSession = (): AuthSession | null => { const raw = localStorage.getItem(storageKey); return raw ? JSON.parse(raw) as AuthSession : null; };
export const setSession = (session: AuthSession | null): void => { if (session) localStorage.setItem(storageKey, JSON.stringify(session)); else localStorage.removeItem(storageKey); };
export const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1", headers: { "Content-Type": "application/json" } });
api.interceptors.request.use((config: InternalAxiosRequestConfig) => { const token = getSession()?.access_token; if (token) config.headers.Authorization = `Bearer ${token}`; return config; });
let refreshPromise: Promise<AuthSession> | null = null;
api.interceptors.response.use((response) => response, async (error: AxiosError) => {
  const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean };
  if (error.response?.status !== 401 || original._retry || original.url?.includes("/auth/refresh")) return Promise.reject(error);
  const previous = getSession(); if (!previous) return Promise.reject(error); original._retry = true;
  refreshPromise ??= axios.post<AuthSession>(`${api.defaults.baseURL}/auth/refresh`, { refresh_token: previous.refresh_token }).then(({ data }) => { setSession(data); return data; }).finally(() => { refreshPromise = null; });
  try { const next = await refreshPromise; original.headers.Authorization = `Bearer ${next.access_token}`; return api(original); } catch { setSession(null); window.location.assign("/login"); return Promise.reject(error); }
});
