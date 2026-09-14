from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.repositories.identity import UserRepository
from app.repositories.reports import ReportRepository
from app.schemas.reports import CustomerReport, InventoryReport, OrderReport, PaymentReport
from app.services.auth_service import permissions_for


class ReportService:
    def __init__(self, db: Session, context: TenantContext) -> None:
        self.db, self.context = db, context
        self.repository = ReportRepository(db, context.business_id)

    def authorize(self) -> None:
        actor = UserRepository(self.db).by_id_with_access(self.context.business_id, self.context.user_id)
        if not actor or "reports.view" not in permissions_for(actor):
            raise AppError(403, "You do not have permission to perform this action.")

    @staticmethod
    def date_bounds(start_date: date | None, end_date: date | None) -> tuple[datetime | None, datetime | None]:
        if start_date and end_date and start_date > end_date:
            raise AppError(422, "start_date must be on or before end_date.")
        start = datetime.combine(start_date, time.min, tzinfo=UTC) if start_date else None
        end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC) if end_date else None
        return start, end

    def orders(self, start_date: date | None, end_date: date | None, status: str | None,
               customer_id, search: str, page: int, page_size: int) -> OrderReport:
        self.authorize()
        start, end = self.date_bounds(start_date, end_date)
        return OrderReport.model_validate(self.repository.orders(start, end, status, customer_id, search, page, page_size))

    def payments(self, start_date: date | None, end_date: date | None, status: str | None,
                 method: str | None, order_id, search: str, page: int, page_size: int) -> PaymentReport:
        self.authorize()
        start, end = self.date_bounds(start_date, end_date)
        return PaymentReport.model_validate(self.repository.payments(start, end, status, method, order_id, search, page, page_size))

    def inventory(self, status: str | None, search: str, page: int, page_size: int) -> InventoryReport:
        self.authorize()
        return InventoryReport.model_validate(self.repository.inventory(status, search, page, page_size))

    def customers(self, start_date: date | None, end_date: date | None, status: str | None,
                  search: str, page: int, page_size: int) -> CustomerReport:
        self.authorize()
        start, end = self.date_bounds(start_date, end_date)
        return CustomerReport.model_validate(self.repository.customers(start, end, status, search, page, page_size))
