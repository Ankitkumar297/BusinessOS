import { useState, type FormEvent } from "react";
import { Button, Card, Input } from "../../components/ui";
import type { Customer, CustomerWrite } from "./types";

const blank: CustomerWrite = { customer_type: "individual", display_name: "", company_name: null, email: null, phone: null, alternate_phone: null, address_line_1: null, address_line_2: null, city: null, state: null, postal_code: null, country: null, tax_id: null, notes: null };
const text = (form: FormData, key: string): string | null => String(form.get(key) ?? "").trim() || null;

export function CustomerForm({ customer, saving, submit, cancel }: { customer?: Customer; saving: boolean; submit: (value: CustomerWrite) => void; cancel: () => void }): JSX.Element {
  const [errors, setErrors] = useState<Record<string, string>>({}); const source = customer ?? blank;
  function save(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault(); const form = new FormData(event.currentTarget); const displayName = text(form, "display_name") ?? ""; const email = text(form, "email");
    const next: Record<string, string> = {};
    if (displayName.length < 2) next.display_name = "Enter at least two characters.";
    if (email && !/^\S+@\S+\.\S+$/.test(email)) next.email = "Enter a valid email address.";
    setErrors(next); if (Object.keys(next).length) return;
    submit({ customer_type: String(form.get("customer_type")) as CustomerWrite["customer_type"], display_name: displayName, company_name: text(form, "company_name"), email, phone: text(form, "phone"), alternate_phone: text(form, "alternate_phone"), address_line_1: text(form, "address_line_1"), address_line_2: text(form, "address_line_2"), city: text(form, "city"), state: text(form, "state"), postal_code: text(form, "postal_code"), country: text(form, "country"), tax_id: text(form, "tax_id"), notes: text(form, "notes") });
  }
  return <form noValidate onSubmit={save} className="space-y-6"><Card><h2 className="mb-4 text-lg font-semibold">Customer overview</h2><div className="grid gap-4 md:grid-cols-2"><label className="block"><span className="label">Customer type</span><select className="field" name="customer_type" defaultValue={source.customer_type}><option value="individual">Individual</option><option value="business">Business</option></select></label><Input label="Display name" name="display_name" required minLength={2} maxLength={160} defaultValue={source.display_name} error={errors.display_name} /><Input label="Company name" name="company_name" maxLength={160} defaultValue={source.company_name ?? ""} /><Input label="Tax / GST / VAT ID" name="tax_id" maxLength={100} defaultValue={source.tax_id ?? ""} /></div></Card>
    <Card><h2 className="mb-4 text-lg font-semibold">Contact information</h2><div className="grid gap-4 md:grid-cols-2"><Input label="Email address" name="email" type="email" maxLength={320} defaultValue={source.email ?? ""} error={errors.email} /><Input label="Phone" name="phone" maxLength={40} defaultValue={source.phone ?? ""} /><Input label="Alternate phone" name="alternate_phone" maxLength={40} defaultValue={source.alternate_phone ?? ""} /></div></Card>
    <Card><h2 className="mb-4 text-lg font-semibold">Address</h2><div className="grid gap-4 md:grid-cols-2"><Input label="Address line 1" name="address_line_1" maxLength={160} defaultValue={source.address_line_1 ?? ""} /><Input label="Address line 2" name="address_line_2" maxLength={160} defaultValue={source.address_line_2 ?? ""} /><Input label="City" name="city" maxLength={100} defaultValue={source.city ?? ""} /><Input label="State / region" name="state" maxLength={100} defaultValue={source.state ?? ""} /><Input label="Postal code" name="postal_code" maxLength={32} defaultValue={source.postal_code ?? ""} /><Input label="Country" name="country" maxLength={100} defaultValue={source.country ?? ""} /></div></Card>
    <Card><label className="block"><span className="label">Internal notes</span><textarea className="field min-h-28" name="notes" maxLength={4000} defaultValue={source.notes ?? ""} /></label></Card><div className="flex gap-3"><Button disabled={saving}>{saving ? "Saving…" : "Save customer"}</Button><button type="button" className="rounded-lg px-4 py-2.5 text-sm font-semibold text-gray-600" onClick={cancel}>Cancel</button></div></form>;
}
