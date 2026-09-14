export interface Business { id: string; name: string; slug: string }
export interface User { id: string; email: string; full_name: string; business_id: string; roles: string[]; permissions: string[] }
export interface AuthSession { access_token: string; refresh_token: string; token_type: string; user: User; business: Business }
