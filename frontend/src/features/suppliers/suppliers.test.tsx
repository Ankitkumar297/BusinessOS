import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { MemoryRouter } from "react-router-dom";
import { AuthContext } from "../auth/auth-store";
import { api } from "../../api/client";
import { SupplierEditor, SuppliersPage } from "./suppliers-page";

vi.mock("../../api/client", () => ({ api: { get: vi.fn(), request: vi.fn() } }));
const supplier = { id: "s1", supplier_name: "Apex Supplies", company_name: "Apex", supplier_code: "APX", contact_person_name: "Taylor", email: "sales@apex.example", phone: "123", alternate_phone: null, address_line_1: null, address_line_2: null, city: null, state: null, postal_code: null, country: "India", tax_id: null, registration_number: null, payment_terms: "Net 30", lead_time_days: 5, minimum_order_value: "100.00", currency: "INR", notes: null, status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" } as const;
function Wrapper({ children, grants = ["suppliers.view", "suppliers.create", "suppliers.update", "suppliers.deactivate", "suppliers.delete"] }: PropsWithChildren<{ grants?: string[] }>): JSX.Element { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); return <MemoryRouter><QueryClientProvider client={client}><AuthContext.Provider value={{ session: null, isLoading: false, can: permission => grants.includes(permission), login: async () => {}, register: async () => {}, logout: async () => {} }}>{children}</AuthContext.Provider></QueryClientProvider></MemoryRouter>; }
beforeEach(() => { vi.clearAllMocks(); HTMLDialogElement.prototype.showModal = function () { this.open = true; }; HTMLDialogElement.prototype.close = function () { this.open = false; }; vi.mocked(api.get).mockResolvedValue({ data: { items: [supplier], total: 1, page: 1, page_size: 20 } }); vi.mocked(api.request).mockResolvedValue({ data: supplier }); }); afterEach(cleanup);

describe("supplier management UX", () => {
  it("renders supplier data and hides restricted actions", async () => { render(<Wrapper grants={["suppliers.view"]}><SuppliersPage /></Wrapper>); expect(await screen.findByText("Apex Supplies")).toBeTruthy(); expect(screen.queryByText("Add supplier")).toBeNull(); expect(screen.queryByText("Edit")).toBeNull(); });
  it("shows empty and error list states", async () => { vi.mocked(api.get).mockResolvedValueOnce({ data: { items: [], total: 0, page: 1, page_size: 20 } }); render(<Wrapper><SuppliersPage /></Wrapper>); expect(await screen.findByText("No suppliers match these filters.")).toBeTruthy(); cleanup(); vi.mocked(api.get).mockRejectedValueOnce(new Error("Network unavailable")); render(<Wrapper><SuppliersPage /></Wrapper>); expect(await screen.findByText("Unable to complete the request. Please try again.")).toBeTruthy(); });
  it("validates and submits a new supplier", async () => { render(<Wrapper><SupplierEditor /></Wrapper>); fireEvent.click(screen.getByText("Save supplier")); expect(await screen.findByText("Enter at least two characters.")).toBeTruthy(); fireEvent.change(document.querySelector('input[name="supplier_name"]')!, { target: { value: "Nova Parts" } }); fireEvent.change(document.querySelector('input[name="email"]')!, { target: { value: "sales@nova.example" } }); fireEvent.click(screen.getByText("Save supplier")); await waitFor(() => expect(api.request).toHaveBeenCalledWith(expect.objectContaining({ method: "post", url: "/suppliers", data: expect.objectContaining({ supplier_name: "Nova Parts", email: "sales@nova.example" }) }))); });
});
