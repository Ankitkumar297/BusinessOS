export type CustomerType = "individual" | "business";
export type CustomerStatus = "active" | "inactive";

export interface Customer {
  id: string; business_id: string; customer_type: CustomerType; display_name: string; company_name: string | null;
  email: string | null; phone: string | null; alternate_phone: string | null; address_line_1: string | null;
  address_line_2: string | null; city: string | null; state: string | null; postal_code: string | null;
  country: string | null; tax_id: string | null; notes: string | null; status: CustomerStatus; created_at: string; updated_at: string;
}

export interface CustomerPage { items: Customer[]; total: number; page: number; page_size: number; }
export type CustomerWrite = Omit<Customer, "id" | "business_id" | "status" | "created_at" | "updated_at">;
