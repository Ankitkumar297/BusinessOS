# Phase 2: Users, roles and permissions

## Scope and design

The existing FastAPI app, UUID identity models, repositories/services, JWT auth,
tenant dependency, React auth provider, Axios client and layout are retained.
Team routes live under `/api/v1`. Business IDs are taken from authenticated
context; request schemas reject extra fields such as a client-provided business ID.

Users are created directly with an initial password (minimum 12 characters).
No invitation email is sent. Existing `full_name` is reused. Email remains globally
unique, preserving Phase 1 email-only login. Soft-deleted identities retain their
email reservation. A deleted custom role retains its name reservation.

## Authorization policy

- Every team endpoint checks a specific backend permission.
- System roles are immutable. Custom roles may be created, edited and soft-deleted.
- Actors cannot grant permissions they do not hold or assign higher privilege roles.
- Only Owners may manage Owners or assign the system Owner role.
- Users cannot change their own assigned roles, modify a role assigned to themselves,
  or deactivate/delete themselves.
- A role assigned to non-deleted users cannot be deleted (inactive users also count).
- Deactivation/deletion revokes refresh tokens and increments the access-token
  generation so reactivation cannot revive an old access token.
- Business row locks serialize team mutations and refresh rotation. Actor permissions
  are reloaded after acquiring the lock, protecting against concurrent revocation.

## Migration

`0002_team` adds `users.auth_version`, seeds granular permissions for existing
businesses, and adds PostgreSQL triggers that reject cross-tenant user-role links
and changes to a user's or role's business ID. It fails rather than silently
retaining corrupt existing links. The old permission codes remain supported.

Run `docker compose up -d --build`. The existing backend startup command applies
Alembic migrations. Back up a paying customer's database before deployment.
Downgrade removes the triggers and token-generation column but retains permission
records/grants to avoid destroying custom grants. SQLite tests do not exercise the
PostgreSQL triggers; use the isolated PostgreSQL suite below.

## API

| Method | Path | Permission |
|---|---|---|
| GET | /users | users.view |
| POST | /users | users.create (and users.assign_roles when assigning roles) |
| GET | /users/{id} | users.view |
| PATCH | /users/{id} | users.update |
| POST | /users/{id}/activate, /users/{id}/deactivate | users.deactivate |
| DELETE | /users/{id} | users.delete |
| GET | /users/{id}/roles | users.view |
| PUT | /users/{id}/roles | users.assign_roles |
| GET | /roles, /roles/{id} | roles.view |
| POST | /roles | roles.create + roles.assign_permissions |
| PATCH | /roles/{id} | roles.update + roles.assign_permissions |
| DELETE | /roles/{id} | roles.delete |
| GET | /permissions, /roles/{id}/permissions | roles.view |
| PUT | /roles/{id}/permissions | roles.assign_permissions |

Paths above are prefixed with `/api/v1`. The user list accepts `search`, `role_id`,
`active`, `page`, `page_size` (1–100). It returns `items`, `total`, `page`, `page_size`.
Role/user responses include assigned roles, permission codes and role member counts.
Member counts use one grouped query per request. Passwords never appear in responses.

## Frontend

`/users` provides search, status/role filters, pagination, profile details, creation,
editing, role assignment, activation/deactivation and soft deletion. `/roles` provides
custom role editing, member/permission counts and grouped permission selection.
`Can` and `PermissionRoute` provide reusable UX guards. Native modal dialogs provide
focus containment and Escape dismissal. Backend authorization remains authoritative.
The query cache is cleared on logout to prevent another account seeing cached team data.

## Events

`TeamEvent` / `publish_team_event` is the post-commit integration boundary for future
audit and notification providers. The current implementation writes real structured
event fields to the application logger. It is not a durable queue or audit database.
Events include user creation/update/status/deletion, role assignments, role
creation/update/deletion and permission changes. No notification or audit UI is added.

## Verification commands

From the backend: `python -m pytest -q` (SQLite service/API tests; PostgreSQL-only tests skip).

From the repository root:

```sh
docker compose -p businessos-phase2-tests -f docker/compose.test.yml up --build --abort-on-container-exit --exit-code-from backend-test
```

This uses a separate PostgreSQL database and temporary per-test schemas. It does not
touch the application's PostgreSQL volume. Tests cover migration startup, user/role
CRUD, permission/role assignment, cross-business access, database triggers, privilege
escalation, stale-token rejection, refresh races and concurrent Owner deactivation.

From the frontend: `npm test`, `npm run lint`, `npm run build`.

## File inventory

New backend files: `core/permissions.py`, `schemas/team.py`, `repositories/team.py`,
`services/team_service.py`, `services/team_events.py`, `api/routes/team.py`,
`alembic/versions/0002_team_management.py`, `tests/test_team.py`,
`tests/test_team_postgres.py`, `tests/__init__.py`, `.dockerignore`.

Modified backend files: identity model, security helpers, auth service, identity
repository, auth dependencies, application router registration, Alembic environment
and configuration, package test dependencies, Dockerfile.

New frontend files: `features/team/{types.ts,permissions.tsx,errors.ts,shared.tsx,
users-page.tsx,roles-page.tsx,team.test.tsx}`, `vitest.config.ts`, `.dockerignore`.

Modified frontend files: router, app layout, auth provider, package manifest/lockfile.
Infrastructure: `docker/compose.test.yml`. Documentation: this file.
