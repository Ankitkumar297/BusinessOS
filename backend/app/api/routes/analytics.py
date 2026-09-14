from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, TenantContext, require_permission
from app.schemas.analytics import AnalyticsRange, DashboardAnalytics
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/dashboard", response_model=DashboardAnalytics)
def dashboard_analytics(db: DbSession, context: Annotated[TenantContext, Depends(require_permission("reports.view"))], range: AnalyticsRange = Query("30d")) -> DashboardAnalytics:
    return AnalyticsService(db, context).dashboard(range)
