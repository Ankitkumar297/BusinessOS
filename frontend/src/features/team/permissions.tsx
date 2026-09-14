import type { PropsWithChildren } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth/use-auth";

export function Can({ permission, children }: PropsWithChildren<{ permission: string }>): JSX.Element | null {
  return useAuth().can(permission) ? <>{children}</> : null;
}
export function PermissionRoute({ permission }: { permission: string }): JSX.Element {
  return useAuth().can(permission) ? <Outlet /> : <Navigate to="/" replace />;
}
