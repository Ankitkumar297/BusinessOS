import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../../api/client";
import { CustomerStatementPage } from "./customer-statement-page";

vi.mock("../../api/client", () => ({ api: { get: vi.fn() } }));

const statement = {
  customer: { id: "customer-1", name: "Ava Patel", company: "Apex Traders", email: "ava@example.com" },
  statement: { start_date: null, end_date: null, opening_balance: "10.01", period_debits: "20.02", period_credits: "5.03", closing_balance: "25.00", pending_payment_total: "4.04" },
  entries: [
    { type: "order_charge", effective_at: "2026-09-01T10:00:00Z", order_id: "order-1", order_number: "SO-101", invoice_id: "invoice-1", invoice_number: "INV-101", payment_id: null, payment_number: null, payment_method: null, debit: "20.02", credit: "0.00", running_balance: "30.03" },
    { type: "payment", effective_at: "2026-09-02T11:00:00Z", order_id: "order-1", order_number: "SO-101", invoice_id: null, invoice_number: null, payment_id: "payment-1", payment_number: "PAY-101", payment_method: "bank_transfer", debit: "0.00", credit: "5.03", running_balance: "25.00" },
  ],
  total: 2,
  page: 1,
  page_size: 20,
};

function renderPage(initial = "/customers/customer-1/statement"): ReturnType<typeof render> {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<MemoryRouter initialEntries={[initial]}><QueryClientProvider client={query}><Routes><Route path="/customers/:customerId/statement" element={<CustomerStatementPage/>}/></Routes></QueryClientProvider></MemoryRouter>);
}

beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.get).mockResolvedValue({ data: statement }); });
afterEach(cleanup);

describe("customer statement page", () => {
  it("requests the routed customer with default pagination and renders authoritative financial data", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Ava Patel" })).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("/reports/customers/customer-1/statement", { params: { start_date: undefined, end_date: undefined, page: 1, page_size: 20 } });
    expect(screen.getByText("Apex Traders")).toBeTruthy();
    expect(screen.getByText("ava@example.com")).toBeTruthy();
    for (const amount of ["₹10.01", "₹20.02", "₹5.03", "₹25.00", "₹4.04", "₹30.03"]) expect(screen.getAllByText(amount).length).toBeGreaterThan(0);
    expect(screen.getByText("Not included in balance")).toBeTruthy();
    expect(screen.getByText("Order charge")).toBeTruthy();
    expect(screen.getAllByText("Payment")).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "SO-101" })[0]?.getAttribute("href")).toBe("/orders/order-1");
    expect(screen.getByRole("link", { name: "INV-101" }).getAttribute("href")).toBe("/invoices/invoice-1");
    expect(screen.getByRole("link", { name: "PAY-101" }).getAttribute("href")).toBe("/payments/payment-1");
    expect(screen.getByText("bank transfer")).toBeTruthy();
    expect(screen.getByRole("link", { name: "← Customer details" }).getAttribute("href")).toBe("/customers/customer-1");
    const paymentRow = screen.getByText("PAY-101").closest("tr")!;
    expect(within(paymentRow).getAllByText("—")).toHaveLength(1);
  });

  it("renders optional customer metadata only when returned", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { ...statement, customer: { ...statement.customer, company: null, email: null } } });
    renderPage();
    expect(await screen.findByText("Ava Patel")).toBeTruthy();
    expect(screen.queryByText("Apex Traders")).toBeNull();
    expect(screen.queryByText("ava@example.com")).toBeNull();
  });

  it("shows loading, retryable failure, and a safe backend 404", async () => {
    vi.mocked(api.get).mockImplementation(() => new Promise(() => {}));
    const loading = renderPage();
    expect(screen.getByRole("status").textContent).toContain("Loading customer statement…");
    loading.unmount();

    vi.mocked(api.get).mockRejectedValueOnce(new Error("Network"));
    renderPage();
    expect(await screen.findByText("Unable to complete the request. Please try again.")).toBeTruthy();
    vi.mocked(api.get).mockResolvedValueOnce({ data: statement });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Ava Patel")).toBeTruthy();
    cleanup();

    vi.mocked(api.get).mockRejectedValueOnce({ isAxiosError: true, response: { status: 404, data: { detail: "Customer not found." } } });
    renderPage();
    expect(await screen.findByText("Customer not found.")).toBeTruthy();
  });

  it("keeps header and summaries visible for an empty statement", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { ...statement, entries: [], total: 0 } });
    renderPage();
    expect(await screen.findByText("No statement activity matches this period.")).toBeTruthy();
    expect(screen.getByText("Ava Patel")).toBeTruthy();
    expect(screen.getByText("₹10.01")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Next" }).hasAttribute("disabled")).toBe(true);
  });

  it("applies start-only, end-only, and both-date filters and clears them", async () => {
    renderPage();
    await screen.findByText("Ava Patel");
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-09-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith(expect.any(String), { params: expect.objectContaining({ start_date: "2026-09-01", end_date: undefined, page: 1 }) }));
    await screen.findByText("Ava Patel");

    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-30" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith(expect.any(String), { params: expect.objectContaining({ start_date: undefined, end_date: "2026-09-30", page: 1 }) }));
    await screen.findByText("Ava Patel");

    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-09-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith(expect.any(String), { params: expect.objectContaining({ start_date: "2026-09-01", end_date: "2026-09-30", page: 1 }) }));
    await screen.findByText("Ava Patel");

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith(expect.any(String), { params: { start_date: undefined, end_date: undefined, page: 1, page_size: 20 } }));
    expect((screen.getByLabelText("Start date") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("End date") as HTMLInputElement).value).toBe("");
  });

  it("rejects an invalid local date range without issuing a filtered request", async () => {
    renderPage();
    await screen.findByText("Ava Patel");
    expect(api.get).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(await screen.findByText("Start date must be on or before end date.")).toBeTruthy();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it("requests next and previous pages and displays page-two server values unchanged", async () => {
    const pageTwo = { ...statement, statement: { ...statement.statement, opening_balance: "4321.09", closing_balance: "987.65" }, entries: [{ ...statement.entries[1], running_balance: "987.65" }], total: 21, page: 2 };
    vi.mocked(api.get).mockImplementation(async (_url, config) => {
      const requestParams = config?.params as { page?: number } | undefined;
      return { data: requestParams?.page === 2 ? pageTwo : { ...statement, total: 21 } };
    });
    renderPage();
    await screen.findByText("Ava Patel");
    expect(screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith(expect.any(String), { params: expect.objectContaining({ page: 2 }) }));
    expect(await screen.findByText("₹4321.09")).toBeTruthy();
    expect(screen.getAllByText("₹987.65")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Next" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith(expect.any(String), { params: expect.objectContaining({ page: 1 }) }));
  });

  it("resets pagination when filters apply or clear and preserves Previous on an empty later page", async () => {
    vi.mocked(api.get).mockImplementation(async (_url, config) => {
      const currentPage = (config?.params as { page?: number } | undefined)?.page;
      return { data: currentPage === 2 ? { ...statement, entries: [], total: 21, page: 2 } : { ...statement, total: 21, page: 1 } };
    });
    renderPage();
    await screen.findByText("Ava Patel");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("No statement activity matches this period.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled")).toBe(false);

    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-09-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith(expect.any(String), { params: expect.objectContaining({ start_date: "2026-09-01", page: 1 }) }));
    await screen.findByText("Ava Patel");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("No statement activity matches this period.");
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith(expect.any(String), { params: expect.objectContaining({ start_date: undefined, page: 1 }) }));
  });
});
