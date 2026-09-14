import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Button, Card, Input, Table } from "../../components/ui";
import { errorMessage } from "../team/errors";
import { Feedback } from "../team/shared";

interface AuditLogItem {
  id: string;
  business_id: string;
  actor_user_id: string;
  actor_name_snapshot: string;
  actor_email_snapshot: string;
  action: string;
  entity_type: string;
  entity_id: string;
  entity_display: string | null;
  changed_fields: string[];
  created_at: string;
}

interface AuditLogPage {
  items: AuditLogItem[];
  total: number;
  page: number;
  page_size: number;
}

type AuditFilters = {
  action: string;
  entityType: string;
  start: string;
  end: string;
};

const pageSize = 20;
const initialFilters: AuditFilters = { action: "", entityType: "", start: "", end: "" };
const actions = [
  "user.created", "user.updated", "user.activated", "user.deactivated", "user.deleted", "user.roles_changed",
  "role.created", "role.updated", "role.permissions_changed", "role.deleted",
  "customer.created", "customer.updated", "customer.activated", "customer.deactivated", "customer.deleted",
  "supplier.created", "supplier.updated", "supplier.activated", "supplier.deactivated", "supplier.deleted",
  "product.created", "product.updated", "product.activated", "product.deactivated", "product.deleted",
  "product.supplier_added", "product.supplier_removed", "inventory.adjusted",
  "order.created", "order.updated", "order.confirmed", "order.cancelled",
  "payment.created", "payment.updated", "invoice.issued",
] as const;
const entityTypes = ["user", "role", "customer", "supplier", "product", "inventory", "order", "payment", "invoice"] as const;

const readable = (value: string): string => {
  const words = value.replace(/[._]/g, " ");
  return words ? `${words[0].toUpperCase()}${words.slice(1)}` : words;
};

const requestParams = (filters: AuditFilters, page: number): Record<string, string | number> => ({
  page,
  page_size: pageSize,
  ...(filters.action ? { action: filters.action } : {}),
  ...(filters.entityType ? { entity_type: filters.entityType } : {}),
  ...(filters.start ? { start: filters.start } : {}),
  ...(filters.end ? { end: filters.end } : {}),
});

function Pager({ page, response, setPage }: { page: number; response: AuditLogPage; setPage: (page: number) => void }): JSX.Element {
  return <div className="mt-5 flex items-center justify-between text-sm text-gray-600">
    <span>{response.total} events · Page {response.page}</span>
    <div className="flex gap-3">
      <button disabled={page <= 1} className="disabled:opacity-40" onClick={() => setPage(page - 1)}>Previous</button>
      <button disabled={page * response.page_size >= response.total} className="disabled:opacity-40" onClick={() => setPage(page + 1)}>Next</button>
    </div>
  </div>;
}

export function AuditLogsPage(): JSX.Element {
  const [draftFilters, setDraftFilters] = useState<AuditFilters>({ ...initialFilters });
  const [activeFilters, setActiveFilters] = useState<AuditFilters>({ ...initialFilters });
  const [page, setPage] = useState(1);
  const [validationError, setValidationError] = useState("");
  const auditLogs = useQuery({
    queryKey: ["audit-logs", activeFilters, page],
    queryFn: async () => (await api.get<AuditLogPage>("/audit-logs", { params: requestParams(activeFilters, page) })).data,
  });

  const apply = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (draftFilters.start && draftFilters.end && draftFilters.start > draftFilters.end) {
      setValidationError("Start date must be on or before end date.");
      return;
    }
    setValidationError("");
    setActiveFilters({ ...draftFilters });
    setPage(1);
  };
  const clear = (): void => {
    setDraftFilters({ ...initialFilters });
    setActiveFilters({ ...initialFilters });
    setValidationError("");
    setPage(1);
  };

  return <div className="space-y-6">
    <div><h1 className="text-2xl font-semibold">Audit Logs</h1><p className="mt-1 text-sm text-gray-500">Review important activity across your business.</p></div>
    <Card><form onSubmit={apply} className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
      <label className="label">Action<select className="field" value={draftFilters.action} onChange={event => setDraftFilters({ ...draftFilters, action: event.target.value })}><option value="">All actions</option>{actions.map(action => <option key={action} value={action}>{readable(action)}</option>)}</select></label>
      <label className="label">Entity type<select className="field" value={draftFilters.entityType} onChange={event => setDraftFilters({ ...draftFilters, entityType: event.target.value })}><option value="">All entity types</option>{entityTypes.map(entityType => <option key={entityType} value={entityType}>{readable(entityType)}</option>)}</select></label>
      <Input label="Start date" type="date" value={draftFilters.start} onChange={event => setDraftFilters({ ...draftFilters, start: event.target.value })}/>
      <Input label="End date" type="date" value={draftFilters.end} onChange={event => setDraftFilters({ ...draftFilters, end: event.target.value })}/>
      <div className="flex items-end gap-3"><Button type="submit">Apply filters</Button><button type="button" className="py-2.5 text-sm font-medium text-gray-600" onClick={clear}>Clear filters</button></div>
    </form><div className="mt-3"><Feedback error={validationError || undefined}/></div></Card>

    <Card>
      {auditLogs.isPending ? <p role="status">Loading audit logs…</p> : auditLogs.isError ? <div className="space-y-3"><Feedback error={errorMessage(auditLogs.error)}/><button className="text-sm font-medium text-blue-700" onClick={() => void auditLogs.refetch()}>Retry</button></div> : <>
        <Table columns={["Time", "Actor", "Action", "Entity", "Changed fields"]}>{auditLogs.data.items.map(item => <tr key={item.id}>
          <td className="whitespace-nowrap px-4 py-4 text-xs text-gray-500">{new Date(item.created_at).toLocaleString()}</td>
          <td className="px-4 py-4"><div className="font-medium">{item.actor_name_snapshot}</div><div className="text-xs text-gray-500">{item.actor_email_snapshot}</div></td>
          <td className="px-4 py-4"><span className="inline-flex rounded-full bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">{readable(item.action)}</span></td>
          <td className="px-4 py-4"><div className="font-medium">{item.entity_display ?? readable(item.entity_type)}</div>{item.entity_display && <div className="text-xs text-gray-500">{readable(item.entity_type)}</div>}</td>
          <td className="px-4 py-4">{item.changed_fields.length ? item.changed_fields.map(readable).join(", ") : "—"}</td>
        </tr>)}</Table>
        {!auditLogs.data.items.length && <p className="py-8 text-center text-sm text-gray-500">No audit activity matches these filters.</p>}
        <Pager page={page} response={auditLogs.data} setPage={setPage}/>
      </>}
    </Card>
  </div>;
}
