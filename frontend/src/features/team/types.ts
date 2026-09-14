export interface TeamRole { id: string; name: string; description: string | null; is_system: boolean; permission_codes: string[]; user_count: number }
export interface TeamUser { id: string; full_name: string; email: string; is_active: boolean; created_at: string; updated_at: string; roles: TeamRole[]; permissions: string[] }
export interface UserPage { items: TeamUser[]; total: number; page: number; page_size: number }
export interface Permission { code: string; description: string; group: string }
