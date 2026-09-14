import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Button, Card, Input } from "../../components/ui";
import { Can } from "./permissions";
import { useAuth } from "../auth/use-auth";
import { Dialog, Feedback } from "./shared";
import { errorMessage } from "./errors";
import type { TeamRole, Permission } from "./types";

export function RolesPage(): JSX.Element {
  const auth = useAuth(); const cache = useQueryClient();
  const [editing, setEditing] = useState<TeamRole | "new" | null>(null);
  const [viewing, setViewing] = useState<TeamRole | null>(null);
  const [deleting, setDeleting] = useState<TeamRole | null>(null);
  const [selected, setSelected] = useState<string[]>([]); const [success, setSuccess] = useState("");
  const roles = useQuery({ queryKey: ["team-roles"], queryFn: async () => (await api.get<TeamRole[]>("/roles")).data });
  const permissions = useQuery({ queryKey: ["team-permissions"], queryFn: async () => (await api.get<Permission[]>("/permissions")).data });
  const mutation = useMutation({ mutationFn: async (request: { method: "post" | "patch" | "delete"; url: string; data?: unknown }) => api.request(request), onSuccess: async () => {
    await Promise.all([cache.invalidateQueries({ queryKey: ["team-roles"] }), cache.invalidateQueries({ queryKey: ["team-users"] })]); setEditing(null); setDeleting(null); setSuccess("Role changes saved.");
  } });
  const categories = [...new Set(permissions.data?.map(p => p.group) ?? [])];
  function save(event: FormEvent<HTMLFormElement>): void { event.preventDefault(); const fields = new FormData(event.currentTarget); mutation.mutate({ method: editing === "new" ? "post" : "patch", url: editing === "new" ? "/roles" : `/roles/${editing && editing.id}`, data: { name: fields.get("name"), description: fields.get("description"), permission_codes: selected } }); }
  function edit(role: TeamRole | "new"): void { mutation.reset(); setEditing(role); setSelected(role === "new" ? [] : role.permission_codes); }
  return <div className="space-y-6"><div className="flex items-center justify-between gap-4"><div><h1 className="text-2xl font-semibold">Roles & permissions</h1><p className="mt-1 text-sm text-gray-500">Define what each team member can access.</p></div><Can permission="roles.create"><Can permission="roles.assign_permissions"><Button onClick={() => edit("new")}>Create role</Button></Can></Can></div><Feedback success={success} />
    {roles.isPending ? <p role="status">Loading roles…</p> : roles.isError ? <Feedback error={errorMessage(roles.error)} /> : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{roles.data.map(role => <Card key={role.id}><div className="flex items-center justify-between"><button className="text-lg font-semibold" onClick={() => setViewing(role)}>{role.name}</button>{role.is_system && <span className="rounded-full bg-blue-50 px-2 py-1 text-xs text-blue-700">System</span>}</div><p className="mt-2 min-h-10 text-sm text-gray-500">{role.description || "Custom business role"}</p><p className="mt-4 text-sm">{role.user_count} members · {role.permission_codes.length} permissions</p><div className="mt-5 flex gap-4 text-sm font-medium text-blue-700"><button onClick={() => setViewing(role)}>View permissions</button>{!role.is_system && <><Can permission="roles.update"><Can permission="roles.assign_permissions"><button onClick={() => edit(role)}>Edit</button></Can></Can><Can permission="roles.delete"><button className="text-red-600" onClick={() => { mutation.reset(); setDeleting(role); }}>Delete</button></Can></>}</div></Card>)}</div>}
    {editing && <Dialog title={editing === "new" ? "Create custom role" : "Edit custom role"} close={() => { if (!mutation.isPending) setEditing(null); }}><form onSubmit={save} className="space-y-5"><Input label="Role name" name="name" required minLength={2} maxLength={80} defaultValue={editing === "new" ? "" : editing.name} /><Input label="Description" name="description" maxLength={255} defaultValue={editing === "new" ? "" : editing.description ?? ""} /><h3 className="font-semibold">Permissions</h3><p className="text-xs text-gray-500">You can only grant permissions you currently hold. Permissions for future modules do not enable those modules.</p>
      {permissions.isPending ? <p>Loading permissions…</p> : permissions.isError ? <Feedback error={errorMessage(permissions.error)} /> : categories.map(group => <fieldset key={group} className="rounded-lg border p-4"><legend className="px-2 text-sm font-semibold capitalize">{group}</legend><div className="grid gap-3 sm:grid-cols-2">{permissions.data?.filter(p => p.group === group).map(p => <label key={p.code} className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" disabled={!auth.can(p.code)} checked={selected.includes(p.code)} onChange={e => setSelected(e.target.checked ? [...selected, p.code] : selected.filter(code => code !== p.code))} /><span>{p.description}<small className="block text-gray-400">{p.code}</small></span></label>)}</div></fieldset>)}<Feedback error={mutation.isError ? errorMessage(mutation.error) : undefined} /><Button disabled={mutation.isPending || !permissions.data}>{mutation.isPending ? "Saving…" : "Save role"}</Button></form></Dialog>}
    {viewing && <Dialog title={viewing.name} close={() => setViewing(null)}><p className="mb-4 text-sm text-gray-500">{viewing.description}</p><div className="flex flex-wrap gap-2">{viewing.permission_codes.map(p => <span key={p} className="rounded bg-gray-100 px-2 py-1 text-xs">{p}</span>)}{!viewing.permission_codes.length && <p>No permissions assigned.</p>}</div></Dialog>}
    {deleting && <Dialog title="Delete custom role" close={() => { if (!mutation.isPending) setDeleting(null); }}><p className="text-sm">Delete {deleting.name}? Roles assigned to members cannot be deleted.</p><Feedback error={mutation.isError ? errorMessage(mutation.error) : undefined} /><Button className="mt-4" disabled={mutation.isPending} onClick={() => mutation.mutate({ method: "delete", url: `/roles/${deleting.id}` })}>{mutation.isPending ? "Deleting…" : "Delete role"}</Button></Dialog>}
  </div>;
}
