from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.repositories.analytics import AnalyticsRepository
from app.repositories.identity import UserRepository
from app.schemas.analytics import DashboardAnalytics
from app.services.auth_service import permissions_for

RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}


class AnalyticsService:
    def __init__(self, db: Session, context: TenantContext) -> None:
        self.db, self.context = db, context
        self.repository = AnalyticsRepository(db, context.business_id)

    def dashboard(self, selected_range: str) -> DashboardAnalytics:
        actor = UserRepository(self.db).by_id_with_access(self.context.business_id, self.context.user_id)
        if not actor or "reports.view" not in permissions_for(actor):
            raise AppError(403, "You do not have permission to perform this action.")
        period_start = datetime.now(UTC) - timedelta(days=RANGE_DAYS[selected_range])
        return DashboardAnalytics(range=selected_range, period_start=period_start, summary=self.repository.summary(), orders=self.repository.orders(period_start), payments=self.repository.payments(period_start), inventory=self.repository.inventory(), customers=self.repository.customers(), recent_activity=self.repository.recent(period_start))
