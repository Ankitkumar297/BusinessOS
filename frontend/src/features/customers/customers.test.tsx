import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthContext } from "../auth/auth-store";
import { api } from "../../api/client";
import { CustomerDetailsPage, CustomerEditorPage, CustomersPage } from "./customers-pages";
import { CustomerStatementPage } from "../customer-statements/customer-statement-page";
import { PermissionRoute } from "../team/permissions";

vi.mock("../../api/client", () => ({ api: { get: vi.fn(), request: vi.fn() } }));
const customer = { id: "c1", business_id: "b1", customer_type: "business", display_name: "Apex Store", company_name: "Apex", email: "contact@apex.example", phone: "123", alternate_phone: null, address_line_1: null, address_line_2: null, city: null, state: null, postal_code: null, country: null, tax_id: null, notes: null, status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" } as const;
function Wrapper({ children, grants = ["customers.view", "customers.create", "customers.update", "customers.deactivate", "customers.delete"], initial = "/" }: PropsWithChildren<{ grants?: string[]; initial?: string }>): JSX.Element { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); return <MemoryRouter initialEntries={[initial]}><QueryClientProvider client={client}><AuthContext.Provider value={{ session: null, isLoading: false, can: permission => grants.includes(permission), login: async () => {}, register: async () => {}, logout: async () => {} }}>{children}</AuthContext.Provider></QueryClientProvider></MemoryRouter>; }
beforeEach(() => { vi.clearAllMocks(); HTMLDialogElement.prototype.showModal = function () { this.open = true; }; HTMLDialogElement.prototype.close = function () { this.open = false; }; vi.mocked(api.get).mockResolvedValue({ data: { items: [customer], total: 1, page: 1, page_size: 20 } }); vi.mocked(api.request).mockResolvedValue({ data: customer }); });
afterEach(cleanup);

describe("customer management UX", () => {
  it("renders customer data and hides actions without permissions", async () => { render(<Wrapper grants={["customers.view"]}><CustomersPage /></Wrapper>); expect(await screen.findByText("Apex Store")).toBeTruthy(); expect(screen.queryByText("Add customer")).toBeNull(); expect(screen.queryByText("Edit")).toBeNull(); });
  it("shows empty and error list states", async () => { vi.mocked(api.get).mockResolvedValueOnce({ data: { items: [], total: 0, page: 1, page_size: 20 } }); render(<Wrapper><CustomersPage /></Wrapper>); expect(await screen.findByText("No customers match these filters.")).toBeTruthy(); cleanup(); vi.mocked(api.get).mockRejectedValueOnce(new Error("Network unavailable")); render(<Wrapper><CustomersPage /></Wrapper>); expect(await screen.findByText("Unable to complete the request. Please try again.")).toBeTruthy(); });
  it("validates then submits a new customer", async () => { render(<Wrapper><CustomerEditorPage /></Wrapper>); fireEvent.click(screen.getByText("Save customer")); expect(await screen.findByText("Enter at least two characters.")).toBeTruthy(); fireEvent.change(document.querySelector('input[name="display_name"]')!, { target: { value: "Ava Patel" } }); fireEvent.change(document.querySelector('input[name="email"]')!, { target: { value: "ava@example.com" } }); fireEvent.click(screen.getByText("Save customer")); await waitFor(() => expect(api.request).toHaveBeenCalledWith(expect.objectContaining({ method: "post", url: "/customers", data: expect.objectContaining({ display_name: "Ava Patel", email: "ava@example.com" }) }))); });
  it("adds a reports-gated statement action without changing customer detail content or edit behavior", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: customer });
    const allowed = render(<Wrapper grants={["customers.view", "customers.update", "reports.view"]} initial="/customers/c1"><Routes><Route path="/customers/:customerId" element={<CustomerDetailsPage/>}/></Routes></Wrapper>);
    expect(await screen.findByRole("heading", { name: "Apex Store" })).toBeTruthy();
    expect(screen.getByText("Customer overview")).toBeTruthy();
    expect(screen.getByText("Contact information")).toBeTruthy();
    expect(screen.getByRole("link", { name: "View statement" }).getAttribute("href")).toBe("/customers/c1/statement");
    expect(screen.getByRole("link", { name: "Edit customer" }).getAttribute("href")).toBe("/customers/c1/edit");
    allowed.unmount();

    render(<Wrapper grants={["customers.view", "customers.update"]} initial="/customers/c1"><Routes><Route path="/customers/:customerId" element={<CustomerDetailsPage/>}/></Routes></Wrapper>);
    expect(await screen.findByRole("heading", { name: "Apex Store" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "View statement" })).toBeNull();
    expect(screen.getByRole("link", { name: "Edit customer" })).toBeTruthy();
  });

  it("guards the statement route only with reports.view and preserves customer and fallback routing", async () => {
    const statement = { customer: { id: "c1", name: "Apex Store", company: "Apex", email: "contact@apex.example" }, statement: { start_date: null, end_date: null, opening_balance: "0.00", period_debits: "0.00", period_credits: "0.00", closing_balance: "0.00", pending_payment_total: "0.00" }, entries: [], total: 0, page: 1, page_size: 20 };
    vi.mocked(api.get).mockImplementation(async url => ({ data: url.includes("/statement") ? statement : customer }));
    const routes = <Routes><Route path="/" element={<p>Home</p>}/><Route element={<PermissionRoute permission="customers.view"/>}><Route path="/customers/:customerId" element={<CustomerDetailsPage/>}/></Route><Route element={<PermissionRoute permission="reports.view"/>}><Route path="/customers/:customerId/statement" element={<CustomerStatementPage/>}/></Route><Route path="*" element={<Navigate to="/" replace/>}/></Routes>;

    const reportOnly = render(<Wrapper grants={["reports.view"]} initial="/customers/c1/statement">{routes}</Wrapper>);
    expect(await screen.findByText("Customer statement")).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("/reports/customers/c1/statement", expect.any(Object));
    reportOnly.unmount();

    const customerOnly = render(<Wrapper grants={["customers.view"]} initial="/customers/c1/statement">{routes}</Wrapper>);
    expect(await screen.findByText("Home")).toBeTruthy();
    expect(screen.queryByText("Customer statement")).toBeNull();
    customerOnly.unmount();

    const customerRoute = render(<Wrapper grants={["customers.view"]} initial="/customers/c1">{routes}</Wrapper>);
    expect(await screen.findByRole("heading", { name: "Apex Store" })).toBeTruthy();
    customerRoute.unmount();

    render(<Wrapper grants={[]} initial="/unknown">{routes}</Wrapper>);
    expect(await screen.findByText("Home")).toBeTruthy();
  });
});
