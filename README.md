# BusinessOS

BusinessOS is a production-oriented, multi-tenant business management SaaS platform for managing the operational workflow from customers and suppliers through inventory, orders, payments, invoices, reporting, statements, and audit history.

Built by **Ankit Kumar**.

## Features

- Secure registration, login, JWT access tokens, refresh-token rotation, and session invalidation
- Business-level tenant isolation enforced throughout the API and data-access layers
- Role-based access control with users, roles, permissions, assignment safeguards, and owner protection
- Customer and supplier management with search, filtering, status controls, and soft deletion
- Product catalog, supplier associations, inventory tracking, stock adjustments, and immutable movement history
- Order creation and confirmation with server-calculated `Decimal` totals and atomic inventory deduction
- Partial and full payments with concurrency-safe overpayment protection
- Immutable invoice snapshots, derived payment state, and downloadable PDF invoices
- Dashboard analytics, operational reports, and CSV report exports
- Customer statements derived from invoice and payment activity
- Tenant-scoped audit logs for security-sensitive and business-domain activity
- Permission-aware React navigation and actions backed by authoritative server-side enforcement

## Technology stack

### Backend

- Python 3.12
- FastAPI and Pydantic
- SQLAlchemy 2 and Alembic
- PostgreSQL 16
- Redis 7
- JWT authentication with Argon2 password hashing
- ReportLab for invoice PDF generation
- Pytest for local and PostgreSQL integration testing

### Frontend

- React 18 and TypeScript
- React Router
- TanStack Query
- Axios
- Tailwind CSS
- Vite, Vitest, and Testing Library

### Infrastructure

- Docker and Docker Compose
- Nginx for the production frontend image
- Isolated PostgreSQL test infrastructure

## Architecture overview

BusinessOS is organized as a single repository with independently deployable backend and frontend applications:

```text
BusinessOS/
├── backend/
│   ├── alembic/          # Database migrations
│   ├── app/
│   │   ├── api/          # FastAPI routes and dependencies
│   │   ├── core/         # Configuration, security, and errors
│   │   ├── db/           # SQLAlchemy session and base setup
│   │   ├── models/       # Tenant-owned domain models
│   │   ├── repositories/ # Tenant-scoped data access
│   │   ├── schemas/      # Request and response contracts
│   │   └── services/     # Business rules and transactions
│   └── tests/            # Local and PostgreSQL tests
├── frontend/
│   └── src/
│       ├── app/          # Router and application providers
│       ├── components/   # Shared UI components
│       ├── features/     # Business feature modules
│       ├── layouts/      # Authenticated application layout
│       └── lib/          # API client and shared utilities
├── docker/               # Isolated test Compose configuration
├── docs/                 # Architecture and security notes
└── docker-compose.yml    # Local full-stack environment
```

HTTP routes stay thin, services own business rules and transaction boundaries, and repositories require tenant identifiers for tenant-owned data access. PostgreSQL constraints and triggers add database-level protection for critical tenant relationships and immutable ownership fields.

## Prerequisites

- Docker Desktop with Docker Compose, or
- Python 3.12, PostgreSQL 16, Redis 7, and Node.js 22 for fully local development

## Environment setup

Create a local environment file from the safe template:

```powershell
Copy-Item .env.example .env
```

Replace every placeholder secret before starting the application. Never commit `.env`; it is excluded by `.gitignore`.

The main settings include PostgreSQL and Redis connection details, the JWT signing secret, token lifetimes, backend CORS origins, and the frontend API base URL.

## Quick start with Docker

From the repository root:

```powershell
docker compose up --build
```

Once the services are healthy:

- Web application: [http://localhost:5173](http://localhost:5173)
- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
- API health: [http://localhost:8000/health](http://localhost:8000/health)

The backend container applies pending Alembic migrations before starting the API. The first registered business user becomes its owner.

Stop the stack without deleting database volumes:

```powershell
docker compose stop
```

## Local development

### Backend

From `backend/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

The backend reads its configuration from environment variables or `backend/.env`. Ensure PostgreSQL and Redis are reachable before starting it.

### Frontend

From `frontend/`:

```powershell
npm ci
npm run dev
```

Vite serves the development application at `http://localhost:5173` by default.

## Database migrations

Run Alembic commands from `backend/` with `DATABASE_URL` configured:

```powershell
alembic current
alembic upgrade head
```

Migration history is append-only. Do not rewrite migrations that may already have been applied to shared environments.

## Testing and quality checks

### Backend local suite

```powershell
Set-Location backend
python -m pytest -q
```

PostgreSQL-only tests are intentionally skipped when a PostgreSQL test URL is not configured.

### Backend PostgreSQL suite

From the repository root:

```powershell
docker compose -p businessos-tests -f docker/compose.test.yml up --build --abort-on-container-exit --exit-code-from backend-test
```

The test Compose project is isolated from the local development database.

### Frontend suite

```powershell
Set-Location frontend
npm test
npm run lint
npm run build
```

The production build includes TypeScript compilation and the Vite bundle.

## API documentation

FastAPI publishes interactive OpenAPI documentation while the backend is running:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI schema: `http://localhost:8000/openapi.json`

Application endpoints are versioned under `/api/v1`. Health probes remain available at `/health`, `/health/live`, and `/health/ready`.

## Security model

- The authenticated server context determines the current business; clients cannot choose an authoritative tenant identifier.
- Backend permission dependencies are authoritative. Frontend permission checks improve usability but never replace API enforcement.
- Tenant-owned repository lookups include both the resource identifier and current business identifier.
- Composite foreign keys, uniqueness constraints, immutable-tenant triggers, and row locks protect sensitive PostgreSQL workflows.
- Issued invoice snapshots and stock-movement history preserve historical business records.
- Refresh tokens are stored as hashes and protected by rotation and concurrency controls.
- Secrets belong in local environment variables or a deployment secret manager, never in source control.

See [docs/architecture.md](docs/architecture.md) and [docs/security.md](docs/security.md) for additional notes.

## Deployment notes

- Use strong, unique production credentials and a long random JWT signing secret.
- Restrict CORS to the deployed frontend origin.
- Terminate TLS at a trusted reverse proxy or platform load balancer.
- Run Alembic migrations as a controlled deployment step before serving traffic.
- Use managed PostgreSQL and Redis services with backups, monitoring, and least-privilege network access.
- Build immutable backend and frontend images from reviewed commits.
- Do not use the development credential fallbacks from `docker-compose.yml` in production.

## License

No open-source license has been selected for this repository. Copyright © Ankit Kumar. All rights reserved.
