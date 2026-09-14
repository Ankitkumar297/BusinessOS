# BusinessOS architecture

The API is layered as routes, dependencies, services, repositories, and SQLAlchemy persistence. Routes only validate transport concerns and call services. Services own transactions and workflows. Tenant-owned repositories require a `business_id` filter, and the authenticated tenant context is constructed exclusively from verified JWT claims.

The frontend is a React single-page application. React Query owns server state, while the auth provider owns the session identity and effective permissions. The frontend never connects to PostgreSQL.
