import { createContext } from "react";
import type { AuthSession } from "../../types/auth";

export interface AuthContextValue {
  session: AuthSession | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (businessName: string, fullName: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (permission: string) => boolean;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
