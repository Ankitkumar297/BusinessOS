import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../../api/client";
import { AppLayout } from "../../layouts/app-layout";
import { AuthContext } from "../auth/auth-store";
import { PermissionRoute } from "../team/permissions";
import { AuditLogsPage } from "./audit-logs-page";

vi.mock("../../api/client", () => ({ api: { get: vi.fn() } }));

const auditPage = {
  items: [
    { id: "audit-1", business_id: "business-1", actor_user_id: "user-1", actor_name_snapshot: "Ava Owner", actor_email_snapshot: "ava@example.com", action: "user.roles_changed", entity_type: "user", entity_id: "member-1", entity_display: "Morgan Member", changed_fields: ["roles", "quantity_on_hand"], created_at: "2026-09-13T10:00:00Z" },
    { id: "audit-2", business_id: "business-1", actor_user_id: "user-1", actor_name_snapshot: "Ava Owner", actor_email_snapshot: "ava@example.com", action: "invoice.issued", entity_type: "invoice", entity_id: "invoice-1", entity_display: null, changed_fields: [], created_at: "2026-09-13T09:00:00Z" },
  ],
  total: 21,
  page: 1,
  page_size: 20,
};

function authValue(permissions = ["audit.view"]) {
  return {
    session: { user: { id: "user-1", email: "ava@example.com", full_name: "Ava Owner", business_id: "business-1", roles: ["Owner"], permissions }, business: { id: "business-1", name: "Alpha", slug: "alpha" }, access_token: "token", refresh_token: "refresh", token_type: "bearer" },
    isLoading: false,
    can: (permission: string) => permissions.includes(permission),
    login: async () => {}, register: async () => {}, logout: async () => {},
  };
}

function Wrapper({ children = <AuditLogsPage/>, permissions = ["audit.view"] }: { children?: JSX.Element; permissions?: string[] }): JSX.Element {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <MemoryRouter><QueryClientProvider client={queryClient}><AuthContext.Provider value={authValue(permissions)}>{children}</AuthContext.Provider></QueryClientProvider></MemoryRouter>;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.get).mockResolvedValue({ data: auditPage });
});
afterEach(cleanup);

describe("audit logs viewer", () => {
  it("requests the first page and renders snapshot-based, human-readable audit rows", async () => {
    render(<Wrapper/>);
    expect(screen.getByRole("heading", { name: "Audit Logs" })).toBeTruthy();
    expect(await screen.findByText("Morgan Member")).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("/audit-logs", { params: { page: 1, page_size: 20 } });
    expect(screen.getAllByText("Ava Owner").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ava@example.com").length).toBeGreaterThan(0);
    const memberRow = screen.getByText("Morgan Member").closest("tr")!;
    expect(within(memberRow).getByText("User roles changed")).toBeTruthy();
    expect(screen.getByText("Roles, Quantity on hand")).toBeTruthy();
    const emptyFieldsRow = screen.getAllByText("Invoice issued").find(element => element.tagName === "SPAN")!.closest("tr")!;
    expect(within(emptyFieldsRow).getByText("Invoice issued")).toBeTruthy();
    expect(within(emptyFieldsRow).getByText("Invoice")).toBeTruthy();
    expect(within(emptyFieldsRow).getByText("—")).toBeTruthy();
  });

  it("maps action, entity, and date filters exactly and resets pagination on apply", async () => {
    render(<Wrapper/>);
    await screen.findByText("Morgan Member");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith("/audit-logs", { params: { page: 2, page_size: 20 } }));
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "product.supplier_added" } });
    fireEvent.change(screen.getByLabelText("Entity type"), { target: { value: "product" } });
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-13" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith("/audit-logs", { params: { page: 1, page_size: 20, action: "product.supplier_added", entity_type: "product", start: "2026-09-01", end: "2026-09-13" } }));
  });

  it("clears active filters without sending empty strings", async () => {
    render(<Wrapper/>);
    await screen.findByText("Morgan Member");
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "invoice.issued" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith("/audit-logs", { params: { page: 1, page_size: 20, action: "invoice.issued" } }));
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith("/audit-logs", { params: { page: 1, page_size: 20 } }));
    expect((screen.getByLabelText("Action") as HTMLSelectElement).value).toBe("");
  });

  it("rejects a reversed date range locally without making an invalid request", async () => {
    render(<Wrapper/>);
    await screen.findByText("Morgan Member");
    expect(api.get).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(await screen.findByText("Start date must be on or before end date.")).toBeTruthy();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it("requests the next page and disables pagination at its boundaries", async () => {
    vi.mocked(api.get).mockImplementation(async (_url, config) => {
      const requestedPage = (config?.params as { page: number }).page;
      return { data: { ...auditPage, page: requestedPage, total: 21 } };
    });
    render(<Wrapper/>);
    await screen.findByText("Morgan Member");
    expect(screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith("/audit-logs", { params: { page: 2, page_size: 20 } }));
    expect(await screen.findByText("21 events · Page 2")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled")).toBe(false);
    expect(screen.getByRole("button", { name: "Next" }).hasAttribute("disabled")).toBe(true);
  });

  it("shows the loading and successful empty states", async () => {
    vi.mocked(api.get).mockImplementation(() => new Promise(() => {}));
    const loading = render(<Wrapper/>);
    expect(screen.getByRole("status").textContent).toBe("Loading audit logs…");
    loading.unmount();
    vi.mocked(api.get).mockResolvedValue({ data: { ...auditPage, items: [], total: 0 } });
    render(<Wrapper/>);
    expect(await screen.findByText("No audit activity matches these filters.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Next" }).hasAttribute("disabled")).toBe(true);
  });

  it("shows API errors and retries the current query", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Network"));
    render(<Wrapper/>);
    expect(await screen.findByText("Unable to complete the request. Please try again.")).toBeTruthy();
    vi.mocked(api.get).mockResolvedValueOnce({ data: auditPage });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Morgan Member")).toBeTruthy();
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("gates both navigation and direct route content with audit.view", () => {
    const allowedNav = render(<Wrapper children={<Routes><Route element={<AppLayout/>}><Route index element={<p>Home</p>}/></Route></Routes>}/>);
    expect(screen.getByRole("link", { name: "Audit logs" })).toBeTruthy();
    allowedNav.unmount();
    const deniedNav = render(<Wrapper permissions={[]} children={<Routes><Route element={<AppLayout/>}><Route index element={<p>Home</p>}/></Route></Routes>}/>);
    expect(screen.queryByRole("link", { name: "Audit logs" })).toBeNull();
    deniedNav.unmount();
    render(<Wrapper permissions={[]} children={<Routes><Route path="/" element={<p>Home</p>}/><Route element={<PermissionRoute permission="audit.view"/>}><Route path="audit-logs" element={<p>Private audit logs</p>}/></Route></Routes>}/>);
    expect(screen.getByText("Home")).toBeTruthy();
    expect(screen.queryByText("Private audit logs")).toBeNull();
  });
});
