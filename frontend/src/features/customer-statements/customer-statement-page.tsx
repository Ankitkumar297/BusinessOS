import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Button, Card, Input, Table } from "../../components/ui";
import { errorMessage } from "../team/errors";
import { Feedback } from "../team/shared";

type StatementEntryType = "order_charge" | "payment";
type PaymentMethod = "cash" | "card" | "bank_transfer" | "upi" | "other";

interface StatementCustomer {
  id: string;
  name: string;
  company: string | null;
  email: string | null;
}

interface StatementSummary {
  start_date: string | null;
  end_date: string | null;
  opening_balance: string;
  period_debits: string;
  period_credits: string;
  closing_balance: string;
  pending_payment_total: string;
}

interface StatementEntry {
  type: StatementEntryType;
  effective_at: string;
  order_id: string;
  order_number: string;
  invoice_id: string | null;
  invoice_number: string | null;
  payment_id: string | null;
  payment_number: string | null;
  payment_method: PaymentMethod | null;
  debit: string;
  credit: string;
  running_balance: string;
}

interface CustomerStatement {
  customer: StatementCustomer;
  statement: StatementSummary;
  entries: StatementEntry[];
  total: number;
  page: number;
  page_size: number;
}

type DateFilters = { start_date: string; end_date: string };

const pageSize = 20;
const initialFilters: DateFilters = { start_date: "", end_date: "" };
const money = (value: string): string => `₹${value}`;
const activityLabel = (value: StatementEntryType): string => value === "order_charge" ? "Order charge" : "Payment";
const methodLabel = (value: PaymentMethod): string => value.replaceAll("_", " ");

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }): JSX.Element {
  return <Card className="p-5"><p className="text-sm text-gray-500">{label}</p><p className="mt-2 text-2xl font-semibold text-gray-900">{money(value)}</p>{detail && <p className="mt-1 text-xs text-gray-500">{detail}</p>}</Card>;
}

function Reference({ to, value }: { to?: string; value?: string | null }): JSX.Element {
  return to && value ? <Link className="font-medium text-blue-700" to={to}>{value}</Link> : <>—</>;
}

function Pager({ page, pageSize: size, total, setPage }: { page: number; pageSize: number; total: number; setPage: (page: number) => void }): JSX.Element {
  return <div className="mt-5 flex items-center justify-between text-sm text-gray-600"><span>{total} entries · Page {page}</span><div className="flex gap-3"><button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><button disabled={page * size >= total} onClick={() => setPage(page + 1)}>Next</button></div></div>;
}

export function CustomerStatementPage(): JSX.Element {
  const { customerId = "" } = useParams();
  const [draft, setDraft] = useState<DateFilters>(initialFilters);
  const [active, setActive] = useState<DateFilters>(initialFilters);
  const [page, setPage] = useState(1);
  const [validationError, setValidationError] = useState("");
  const statement = useQuery({
    queryKey: ["reports", "customer-statement", customerId, { start_date: active.start_date, end_date: active.end_date, page, page_size: pageSize }],
    queryFn: async () => (await api.get<CustomerStatement>(`/reports/customers/${customerId}/statement`, { params: { start_date: active.start_date || undefined, end_date: active.end_date || undefined, page, page_size: pageSize } })).data,
  });

  const apply = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (draft.start_date && draft.end_date && draft.start_date > draft.end_date) {
      setValidationError("Start date must be on or before end date.");
      return;
    }
    setValidationError("");
    setActive(draft);
    setPage(1);
  };
  const clear = (): void => {
    setDraft(initialFilters);
    setActive(initialFilters);
    setValidationError("");
    setPage(1);
  };

  if (statement.isPending) return <p role="status">Loading customer statement…</p>;
  if (statement.isError) return <div className="space-y-3"><Feedback error={errorMessage(statement.error)} /><button className="text-sm font-medium text-blue-700" onClick={() => void statement.refetch()}>Retry</button></div>;

  const data = statement.data;
  return <div className="space-y-6">
    <div><Link className="text-sm font-medium text-blue-700" to={`/customers/${customerId}`}>← Customer details</Link><h1 className="mt-3 text-2xl font-semibold">{data.customer.name}</h1>{data.customer.company && <p className="mt-1 text-sm text-gray-600">{data.customer.company}</p>}{data.customer.email && <p className="mt-1 text-sm text-gray-500">{data.customer.email}</p>}<p className="mt-2 text-sm text-gray-500">Customer statement</p></div>
    <Card><form onSubmit={apply} className="grid gap-3 md:grid-cols-3"><Input label="Start date" type="date" value={draft.start_date} onChange={event => setDraft({ ...draft, start_date: event.target.value })}/><Input label="End date" type="date" value={draft.end_date} onChange={event => setDraft({ ...draft, end_date: event.target.value })}/><div className="flex items-end gap-3"><Button type="submit">Apply filters</Button><button type="button" className="py-2.5 text-sm font-medium text-gray-600" onClick={clear}>Clear filters</button></div></form><div className="mt-3"><Feedback error={validationError || undefined}/></div></Card>
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5"><Metric label="Opening balance" value={data.statement.opening_balance}/><Metric label="Period debits" value={data.statement.period_debits}/><Metric label="Period credits" value={data.statement.period_credits}/><Metric label="Closing balance" value={data.statement.closing_balance}/><Metric label="Pending payments" value={data.statement.pending_payment_total} detail="Not included in balance"/></div>
    <Card><h2 className="mb-4 font-semibold">Statement activity</h2><Table columns={["Date", "Activity", "Order", "Invoice", "Payment", "Debit", "Credit", "Running balance"]}>{data.entries.map(entry => <tr key={`${entry.type}-${entry.payment_id ?? entry.order_id}-${entry.effective_at}`}><td className="px-4 py-4 text-xs text-gray-500">{new Date(entry.effective_at).toLocaleString()}</td><td className="px-4 py-4">{activityLabel(entry.type)}</td><td className="px-4 py-4"><Reference to={`/orders/${entry.order_id}`} value={entry.order_number}/></td><td className="px-4 py-4"><Reference to={entry.invoice_id ? `/invoices/${entry.invoice_id}` : undefined} value={entry.invoice_number}/></td><td className="px-4 py-4"><Reference to={entry.payment_id ? `/payments/${entry.payment_id}` : undefined} value={entry.payment_number}/>{entry.payment_method && <div className="mt-1 text-xs text-gray-500">{methodLabel(entry.payment_method)}</div>}</td><td className="px-4 py-4">{money(entry.debit)}</td><td className="px-4 py-4">{money(entry.credit)}</td><td className="px-4 py-4 font-medium">{money(entry.running_balance)}</td></tr>)}</Table>{data.entries.length === 0 && <p className="py-8 text-center text-sm text-gray-500">No statement activity matches this period.</p>}<Pager page={data.page} pageSize={data.page_size} total={data.total} setPage={setPage}/></Card>
  </div>;
}
