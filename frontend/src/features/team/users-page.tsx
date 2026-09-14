import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Button, Card, Input, Table } from "../../components/ui";
import { useAuth } from "../auth/use-auth";
import { Can } from "./permissions";
import { Dialog, Feedback } from "./shared";
import { errorMessage } from "./errors";
import type { TeamUser, TeamRole, UserPage } from "./types";

export function UsersPage(): JSX.Element {
  const auth = useAuth(); const cache = useQueryClient();
  const [search, setSearch] = useState(""); const [role, setRole] = useState(""); const [status, setStatus] = useState(""); const [page, setPage] = useState(1);
  const [editor, setEditor] = useState<TeamUser | "new" | null>(null);
  const [details, setDetails] = useState<TeamUser | null>(null);
  const [assignment, setAssignment] = useState<TeamUser | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [confirm, setConfirm] = useState<{ user: TeamUser; action: string } | null>(null);
  const [success, setSuccess] = useState("");
  const users = useQuery({ queryKey: ["team-users", search, role, status, page], queryFn: async () => (await api.get<UserPage>("/users", { params: { search, role_id: role || undefined, active: status || undefined, page, page_size: 20 } })).data });
  const roles = useQuery({ queryKey: ["team-roles"], enabled: auth.can("roles.view"), queryFn: async () => (await api.get<TeamRole[]>("/roles")).data });
  const mutation = useMutation({ mutationFn: async ({ method, url, data }: { method: "post" | "patch" | "put" | "delete"; url: string; data?: unknown }) => api.request({ method, url, data }),
    onSuccess: async () => { await Promise.all([cache.invalidateQueries({ queryKey: ["team-users"] }), cache.invalidateQueries({ queryKey: ["team-roles"] })]); setEditor(null); setAssignment(null); setConfirm(null); setDetails(null); setSuccess("Team updated successfully."); } });
  function save(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    const fields = { full_name: String(data.get("full_name")), email: String(data.get("email")) };
    if (editor === "new") mutation.mutate({ method: "post", url: "/users", data: { ...fields, password: String(data.get("password")), role_ids: selected } });
    else if (editor) mutation.mutate({ method: "patch", url: `/users/${editor.id}`, data: fields });
  }
  function openEditor(user: TeamUser | "new"): void { mutation.reset(); setSuccess(""); setSelected([]); setEditor(user); }
  const choices = (roles.data ?? []).filter(r => r.permission_codes.every(p => auth.can(p)) && (r.name !== "Owner" || auth.session?.user.roles.includes("Owner")));
  const rolePicker = <fieldset className="space-y-2"><legend className="mb-2 text-sm font-medium">Assigned roles</legend>{roles.isError ? <Feedback error={errorMessage(roles.error)} /> : roles.isPending ? <p>Loading roles…</p> : choices.map(r => <label key={r.id} className="flex items-center gap-2 rounded-lg border p-3 text-sm"><input type="checkbox" checked={selected.includes(r.id)} onChange={e => setSelected(e.target.checked ? [...selected, r.id] : selected.filter(id => id !== r.id))} />{r.name}</label>)}</fieldset>;
  return <div className="space-y-6"><div className="flex flex-wrap items-center justify-between gap-4"><div><h1 className="text-2xl font-semibold">Team members</h1><p className="mt-1 text-sm text-gray-500">Manage the people and access in your business.</p></div><Can permission="users.create"><Button onClick={() => openEditor("new")}>Add team member</Button></Can></div>
    <Feedback success={success} error={!editor && !assignment && !confirm && mutation.isError ? errorMessage(mutation.error) : undefined} />
    <Card><div className="mb-5 grid gap-3 sm:grid-cols-3"><Input label="Search team" type="search" value={search} placeholder="Name or email" onChange={e => { setSearch(e.target.value); setPage(1); }} />
      <label className="label">Role<select className="field" value={role} onChange={e => { setRole(e.target.value); setPage(1); }}><option value="">All roles</option>{roles.data?.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
      <label className="label">Status<select className="field" value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">All statuses</option><option value="true">Active</option><option value="false">Inactive</option></select></label></div>
      {users.isPending ? <p role="status">Loading team…</p> : users.isError ? <><Feedback error={errorMessage(users.error)} /><button onClick={() => void users.refetch()}>Retry</button></> : <>
      <Table columns={["Member", "Roles", "Status", "Actions"]}>{users.data.items.map(user => <tr key={user.id}><td className="px-4 py-4"><div className="flex items-center gap-3"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-blue-50 font-semibold text-blue-700">{user.full_name.split(" ").map(n => n[0]).slice(0, 2).join("")}</span><div><button className="font-medium text-blue-700" onClick={() => setDetails(user)}>{user.full_name}</button><p className="text-xs text-gray-500">{user.email}</p></div></div></td><td className="px-4 py-4">{user.roles.map(r => r.name).join(", ") || "No roles"}</td><td className="px-4 py-4"><span className={`rounded-full px-2 py-1 text-xs ${user.is_active ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-500"}`}>{user.is_active ? "Active" : "Inactive"}</span></td><td className="px-4 py-4"><div className="flex flex-wrap gap-3 text-xs font-medium text-blue-700">
        <Can permission="users.update"><button disabled={mutation.isPending} onClick={() => openEditor(user)}>Edit</button></Can>
        {user.id !== auth.session?.user.id && <><Can permission="users.assign_roles"><button disabled={mutation.isPending} onClick={() => { mutation.reset(); setSelected(user.roles.map(r => r.id)); setAssignment(user); }}>Roles</button></Can><Can permission="users.deactivate"><button disabled={mutation.isPending} onClick={() => { mutation.reset(); setConfirm({ user, action: user.is_active ? "deactivate" : "activate" }); }}>{user.is_active ? "Deactivate" : "Activate"}</button></Can><Can permission="users.delete"><button disabled={mutation.isPending} className="text-red-600" onClick={() => { mutation.reset(); setConfirm({ user, action: "delete" }); }}>Delete</button></Can></>}
      </div></td></tr>)}</Table>{users.data.items.length === 0 && <p className="py-10 text-center text-sm text-gray-500">No team members match these filters.</p>}
      <div className="mt-5 flex items-center justify-between text-sm"><span>{users.data.total} members · Page {page}</span><div className="flex gap-3"><button disabled={page === 1} className="disabled:opacity-40" onClick={() => setPage(page - 1)}>Previous</button><button disabled={page * 20 >= users.data.total} className="disabled:opacity-40" onClick={() => setPage(page + 1)}>Next</button></div></div></>}
    </Card>
    {editor && <Dialog title={editor === "new" ? "Add team member" : "Edit team member"} close={() => { if (!mutation.isPending) setEditor(null); }}><form onSubmit={save} className="space-y-4"><Input label="Full name" name="full_name" required minLength={2} maxLength={160} defaultValue={editor === "new" ? "" : editor.full_name} /><Input label="Email address" name="email" type="email" required defaultValue={editor === "new" ? "" : editor.email} />{editor === "new" && <><Input label="Initial password" name="password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" /><p className="text-xs text-gray-500">Share credentials securely with the team member. No invitation email is sent.</p>{auth.can("users.assign_roles") && auth.can("roles.view") && rolePicker}</>}<Feedback error={mutation.isError ? errorMessage(mutation.error) : undefined} /><Button disabled={mutation.isPending}>{mutation.isPending ? "Saving…" : "Save member"}</Button></form></Dialog>}
    {assignment && <Dialog title={`Roles for ${assignment.full_name}`} close={() => { if (!mutation.isPending) setAssignment(null); }}><div className="space-y-4">{rolePicker}<Feedback error={mutation.isError ? errorMessage(mutation.error) : undefined} /><Button disabled={mutation.isPending || !roles.data} onClick={() => mutation.mutate({ method: "put", url: `/users/${assignment.id}/roles`, data: { role_ids: selected } })}>Save roles</Button></div></Dialog>}
    {details && <Dialog title={details.full_name} close={() => setDetails(null)}><div className="space-y-4 text-sm"><p>{details.email}</p><p>{details.is_active ? "Active" : "Inactive"} · {details.roles.map(r => r.name).join(", ") || "No roles"}</p><p className="text-gray-500">Created {new Date(details.created_at).toLocaleString()}<br />Updated {new Date(details.updated_at).toLocaleString()}</p><h3 className="font-semibold">Effective permissions</h3><div className="flex flex-wrap gap-2">{details.permissions.map(p => <span key={p} className="rounded bg-gray-100 px-2 py-1 text-xs">{p}</span>)}{!details.permissions.length && <p>No permissions assigned.</p>}</div></div></Dialog>}
    {confirm && <Dialog title={`${confirm.action[0].toUpperCase()}${confirm.action.slice(1)} member`} close={() => { if (!mutation.isPending) setConfirm(null); }}><p className="mb-4 text-sm">Confirm {confirm.action} for {confirm.user.full_name}? {confirm.action !== "activate" && "Their access will be disabled."}</p><Feedback error={mutation.isError ? errorMessage(mutation.error) : undefined} /><Button className="mt-4" disabled={mutation.isPending} onClick={() => mutation.mutate({ method: confirm.action === "delete" ? "delete" : "post", url: `/users/${confirm.user.id}${confirm.action === "delete" ? "" : `/${confirm.action}`}` })}>{mutation.isPending ? "Updating…" : "Confirm"}</Button></Dialog>}
  </div>;
}
