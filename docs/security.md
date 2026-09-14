# Security notes

- Passwords use Argon2 hashes.
- Access tokens are short-lived JWTs; refresh tokens are random secrets stored as hashes and rotated on use.
- Refresh-token reuse revokes all active refresh tokens for the affected user.
- Tenant identifiers are sourced from verified access-token claims, never request bodies or route parameters.
- Permission checks happen in FastAPI dependencies before a service is called.
- Production deployments must use HTTPS, a generated JWT secret, a managed PostgreSQL backup policy, and a secure secret manager.
