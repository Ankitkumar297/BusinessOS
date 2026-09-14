import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { AuthContext } from "../auth/auth-store";
import { api } from "../../api/client";
import { Can } from "./permissions";
import { UsersPage } from "./users-page";
import { RolesPage } from "./roles-page";

vi.mock("../../api/client", () => ({ api: { get: vi.fn(), request: vi.fn() } }));
const role = { id: "r1", name: "Support", description: "Support role", is_system: false, permission_codes: ["users.view"], user_count: 0 };
const permissions = ["users.view", "users.create", "users.assign_roles", "roles.view", "roles.create", "roles.assign_permissions"];
function Wrapper({ children, grants = permissions }: PropsWithChildren<{ grants?: string[] }>): JSX.Element {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={client}><AuthContext.Provider value={{ session: null, isLoading: false, can: p => grants.includes(p), login: async () => {}, register: async () => {}, logout: async () => {} }}>{children}</AuthContext.Provider></QueryClientProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: url === "/roles" ? [role] : url === "/permissions" ? [{ code: "users.view", description: "View users", group: "users" }] : { items: [], total: 0, page: 1, page_size: 20 } }));
  vi.mocked(api.request).mockResolvedValue({ data: {} });
});
afterEach(cleanup);

describe("team permission UX", () => {
  it("does not render actions without their permission", () => {
    render(<Wrapper grants={[]}><Can permission="users.create"><button>Add member</button></Can></Wrapper>);
    expect(screen.queryByText("Add member")).toBeNull();
  });
  it("submits a member with selected role and displays success", async () => {
    render(<Wrapper><UsersPage /></Wrapper>);
    fireEvent.click(screen.getByText("Add team member"));
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Test Member" } });
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "member@example.com" } });
    fireEvent.change(screen.getByLabelText("Initial password"), { target: { value: "StrongPassword123!" } });
    fireEvent.click(await screen.findByLabelText("Support"));
    fireEvent.click(screen.getByText("Save member"));
    await waitFor(() => expect(api.request).toHaveBeenCalledWith(expect.objectContaining({ method: "post", url: "/users", data: expect.objectContaining({ full_name: "Test Member", role_ids: ["r1"] }) })));
    expect(await screen.findByText("Team updated successfully.")).toBeTruthy();
  });
  it("groups and submits permissions for a custom role", async () => {
    render(<Wrapper><RolesPage /></Wrapper>);
    fireEvent.click(screen.getByText("Create role"));
    fireEvent.change(screen.getByLabelText("Role name"), { target: { value: "Sales" } });
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(screen.getByText("Save role"));
    await waitFor(() => expect(api.request).toHaveBeenCalledWith(expect.objectContaining({ method: "post", url: "/roles", data: expect.objectContaining({ name: "Sales", permission_codes: ["users.view"] }) })));
  });
});
