import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../../api/client";
import { AppLayout } from "../../layouts/app-layout";
import { AuthContext } from "../auth/auth-store";
import { PermissionRoute } from "../team/permissions";
import { ReportsPage } from "./reports-page";

vi.mock("../../api/client", () => ({ api: { get: vi.fn() } }));

const orders = { items: [{ order_id: "order-1", order_number: "SO-101", customer_id: "customer-1", customer_name: "Ava Patel", status: "confirmed", order_date: "2026-09-10T10:00:00Z", subtotal: "100.10", tax_total: "18.02", grand_total: "118.12", item_count: 2 }], summary: { matching_orders: 21, confirmed_order_count: 14, confirmed_order_value: "1234.56" }, total: 21, page: 1, page_size: 20 };
const payments = { items: [{ payment_id: "payment-1", payment_number: "PAY-101", order_id: "order-1", order_number: "SO-101", amount: "50.10", payment_method: "bank_transfer", status: "completed", paid_at: "2026-09-10T11:00:00Z" }], summary: { matching_payments: 3, completed_count: 2, pending_count: 1, failed_count: 0, cancelled_count: 0, completed_amount: "75.10", pending_amount: "10.20" }, total: 3, page: 1, page_size: 20 };
const inventory = { items: [{ product_id: "product-1", product_name: "Low Widget", sku: "LOW-1", quantity: "2.000", reorder_threshold: "5.000", stock_status: "low_stock" }], summary: { tracked_products: 9, in_stock_count: 6, low_stock_count: 2, out_of_stock_count: 1 }, total: 9, page: 1, page_size: 20 };
const customers = { items: [{ customer_id: "customer-1", customer_name: "Ava Patel", email: "ava@example.com", phone: "111", status: "active", created_at: "2026-09-01T10:00:00Z", order_count: 4, confirmed_order_value: "450.25" }], summary: { matching_customers: 8, active_count: 7, inactive_count: 1, confirmed_order_value: "900.50" }, total: 8, page: 1, page_size: 20 };

function authValue(permissions = ["reports.view"]) { return { session: { user: { id: "u", email: "a@example.com", full_name: "A", business_id: "b", roles: [], permissions }, business: { id: "b", name: "Alpha", slug: "alpha" }, access_token: "x", refresh_token: "y", token_type: "bearer" }, isLoading: false, can: (permission: string) => permissions.includes(permission), login: async () => {}, register: async () => {}, logout: async () => {} }; }
function Wrap({ permissions = ["reports.view"], children = <ReportsPage/> }: { permissions?: string[]; children?: JSX.Element }): JSX.Element { const query = new QueryClient({ defaultOptions: { queries: { retry: false } } }); return <MemoryRouter><QueryClientProvider client={query}><AuthContext.Provider value={authValue(permissions)}>{children}</AuthContext.Provider></QueryClientProvider></MemoryRouter>; }

beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.get).mockImplementation(async url => ({ data: url.endsWith("/export") ? new Blob(["report"], { type: "text/csv" }) : url === "/reports/payments" ? payments : url === "/reports/inventory" ? inventory : url === "/reports/customers" ? customers : orders })); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function mockBrowserDownload(): { createObjectURL: ReturnType<typeof vi.fn>; revokeObjectURL: ReturnType<typeof vi.fn>; downloads: string[]; restore: () => void } {
  const originalCreate = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
  const originalRevoke = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
  const createObjectURL = vi.fn(() => "blob:report");
  const revokeObjectURL = vi.fn();
  const downloads: string[] = [];
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { downloads.push(this.download); });
  return { createObjectURL, revokeObjectURL, downloads, restore: () => { click.mockRestore(); if (originalCreate) Object.defineProperty(URL, "createObjectURL", originalCreate); else Reflect.deleteProperty(URL, "createObjectURL"); if (originalRevoke) Object.defineProperty(URL, "revokeObjectURL", originalRevoke); else Reflect.deleteProperty(URL, "revokeObjectURL"); } };
}

describe("reports", () => {
  it("renders authoritative order rows and aggregates and sends applied filters and pagination", async () => {
    render(<Wrap/>);
    expect(await screen.findByText("SO-101")).toBeTruthy();
    expect(screen.getByText("₹1234.56")).toBeTruthy();
    expect(screen.getByText("₹118.12")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "Ava" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "confirmed" } });
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-10" } });
    fireEvent.click(screen.getByText("Apply filters"));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith("/reports/orders", { params: expect.objectContaining({ search: "Ava", status: "confirmed", start_date: "2026-09-01", end_date: "2026-09-10", page: 1 }) }));
    await screen.findByText("SO-101");
    fireEvent.click(screen.getByText("Next"));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith("/reports/orders", { params: expect.objectContaining({ page: 2, search: "Ava" }) }));
  });

  it("renders payment, inventory, and customer server rows and summary values", async () => {
    render(<Wrap/>); await screen.findByText("SO-101");
    fireEvent.click(screen.getByRole("tab", { name: "Payments" }));
    expect(await screen.findByText("PAY-101")).toBeTruthy(); expect(screen.getByText("₹75.10")).toBeTruthy(); expect(screen.getByText("₹10.20")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Inventory" }));
    expect(await screen.findByText("Low Widget")).toBeTruthy(); expect(screen.getByText("2.000")).toBeTruthy(); expect(screen.getAllByText("Low stock").length).toBeGreaterThan(0); expect(screen.getByText("9")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Customers" }));
    expect(await screen.findByText("ava@example.com")).toBeTruthy(); expect(screen.getByText("₹450.25")).toBeTruthy(); expect(screen.getByText("₹900.50")).toBeTruthy();
  });

  it("shows loading, error with retry, and empty report states", async () => {
    vi.mocked(api.get).mockImplementation(() => new Promise(() => {})); const loading = render(<Wrap/>); expect(screen.getByRole("status").textContent).toContain("Loading report"); loading.unmount(); vi.mocked(api.get).mockClear();
    vi.mocked(api.get).mockRejectedValue(new Error("Network")); const failed = render(<Wrap/>); expect(await screen.findByText("Unable to complete the request. Please try again.")).toBeTruthy(); fireEvent.click(screen.getByText("Retry")); await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2)); failed.unmount();
    vi.mocked(api.get).mockResolvedValue({ data: { ...orders, items: [], total: 0, summary: { matching_orders: 0, confirmed_order_count: 0, confirmed_order_value: "0.00" } } }); render(<Wrap/>); expect(await screen.findByText("No orders match these filters.")).toBeTruthy(); expect(screen.getByText("₹0.00")).toBeTruthy();
  });

  it("protects the route and navigation with reports.view", () => {
    const allowed = render(<Wrap children={<Routes><Route element={<AppLayout/>}><Route index element={<p>Home</p>}/></Route></Routes>}/>); expect(screen.getByRole("link", { name: "Reports" })).toBeTruthy(); allowed.unmount();
    const deniedNav = render(<Wrap permissions={[]} children={<Routes><Route element={<AppLayout/>}><Route index element={<p>Home</p>}/></Route></Routes>}/>); expect(screen.queryByRole("link", { name: "Reports" })).toBeNull(); deniedNav.unmount();
    render(<Wrap permissions={[]} children={<Routes><Route path="/" element={<p>Home</p>}/><Route element={<PermissionRoute permission="reports.view"/>}><Route path="reports" element={<p>Secret reports</p>}/></Route></Routes>}/>); expect(screen.getByText("Home")).toBeTruthy(); expect(screen.queryByText("Secret reports")).toBeNull();
  });

  it("exports Orders with applied filters only, without pagination, and cleans up the Blob download", async () => {
    const download = mockBrowserDownload();
    try {
      render(<Wrap/>);
      await screen.findByText("SO-101");
      fireEvent.change(screen.getByLabelText("Search"), { target: { value: "Ava" } });
      fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
      await waitFor(() => expect(vi.mocked(api.get).mock.calls.some(([url]) => url === "/reports/orders/export")).toBe(true));
      let exportCalls = vi.mocked(api.get).mock.calls.filter(([url]) => url === "/reports/orders/export");
      expect(exportCalls[0]?.[1]).toEqual({ params: expect.objectContaining({ search: undefined }), responseType: "blob" });
      expect(exportCalls[0]?.[1]?.params).not.toHaveProperty("page");
      expect(exportCalls[0]?.[1]?.params).not.toHaveProperty("page_size");

      fireEvent.click(screen.getByText("Apply filters"));
      await waitFor(() => expect(api.get).toHaveBeenCalledWith("/reports/orders", { params: expect.objectContaining({ search: "Ava" }) }));
      fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
      await waitFor(() => expect(vi.mocked(api.get).mock.calls.filter(([url]) => url === "/reports/orders/export")).toHaveLength(2));
      exportCalls = vi.mocked(api.get).mock.calls.filter(([url]) => url === "/reports/orders/export");
      expect(exportCalls[1]?.[1]).toEqual({ params: expect.objectContaining({ search: "Ava" }), responseType: "blob" });
      expect(download.createObjectURL).toHaveBeenCalledTimes(2);
      expect(download.downloads).toEqual(["orders-report.csv", "orders-report.csv"]);
      expect(document.querySelector('a[download="orders-report.csv"]')).toBeNull();
      expect(download.revokeObjectURL).toHaveBeenCalledTimes(2);
    } finally { download.restore(); }
  });

  it("uses the correct export endpoint and filename for every report tab", async () => {
    const download = mockBrowserDownload();
    try {
      render(<Wrap/>);
      await screen.findByText("SO-101");
      fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
      await waitFor(() => expect(download.downloads).toContain("orders-report.csv"));

      for (const [tab, endpoint, filename] of [
        ["Payments", "/reports/payments/export", "payments-report.csv"],
        ["Inventory", "/reports/inventory/export", "inventory-report.csv"],
        ["Customers", "/reports/customers/export", "customers-report.csv"],
      ] as const) {
        fireEvent.click(screen.getByRole("tab", { name: tab }));
        await waitFor(() => expect(vi.mocked(api.get).mock.calls.some(([url]) => url === endpoint.replace("/export", ""))).toBe(true));
        fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
        await waitFor(() => expect(vi.mocked(api.get).mock.calls.some(([url, config]) => url === endpoint && config?.responseType === "blob")).toBe(true));
        expect(download.downloads).toContain(filename);
      }
    } finally { download.restore(); }
  });

  it("keeps export pending and failure state independent from the rendered report", async () => {
    const download = mockBrowserDownload();
    let resolveExport: ((value: { data: Blob }) => void) | undefined;
    const pendingExport = new Promise<{ data: Blob }>(resolve => { resolveExport = resolve; });
    vi.mocked(api.get).mockImplementation(async url => url.endsWith("/export") ? pendingExport : { data: orders });
    try {
      render(<Wrap/>);
      await screen.findByText("SO-101");
      fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
      const pendingButton = await screen.findByRole("button", { name: "Exporting…" });
      expect(pendingButton.hasAttribute("disabled")).toBe(true);
      fireEvent.click(pendingButton);
      expect(vi.mocked(api.get).mock.calls.filter(([url]) => url === "/reports/orders/export")).toHaveLength(1);
      resolveExport?.({ data: new Blob(["report"], { type: "text/csv" }) });
      await screen.findByRole("button", { name: "Export CSV" });

      vi.mocked(api.get).mockImplementation(async url => { if (url.endsWith("/export")) throw new Error("Network"); return { data: orders }; });
      fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
      expect(await screen.findByText("Unable to complete the request. Please try again.")).toBeTruthy();
      expect(screen.getByText("SO-101")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Export CSV" }).hasAttribute("disabled")).toBe(false);
    } finally { download.restore(); }
  });
});
