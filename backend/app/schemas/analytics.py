from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.schemas.team import StrictRequest

AnalyticsRange = Literal["7d", "30d", "90d"]


class DashboardSummary(StrictRequest):
    total_customers: int
    total_products: int
    total_orders: int
    total_invoices: int


class OrderAnalytics(StrictRequest):
    draft_count: int
    confirmed_count: int
    cancelled_count: int
    period_confirmed_count: int
    period_confirmed_order_value: Decimal
    period_average_confirmed_order_value: Decimal


class PaymentAnalytics(StrictRequest):
    completed_count: int
    pending_count: int
    failed_count: int
    cancelled_count: int
    period_completed_amount: Decimal
    period_pending_amount: Decimal
    outstanding_amount: Decimal


class InventoryAnalytics(StrictRequest):
    tracked_products: int
    in_stock_count: int
    low_stock_count: int
    out_of_stock_count: int
    low_stock_products: list["LowStockProduct"]


class LowStockProduct(StrictRequest):
    product_id: UUID
    product_name: str
    sku: str
    quantity: Decimal
    reorder_threshold: Decimal | None
    stock_status: Literal["low_stock", "out_of_stock"]


class CustomerAnalytics(StrictRequest):
    total: int
    active: int
    inactive: int


class RecentRecord(StrictRequest):
    id: UUID
    reference: str
    status: str
    amount: Decimal
    occurred_at: datetime


class RecentActivity(StrictRequest):
    orders: list[RecentRecord]
    payments: list[RecentRecord]
    invoices: list[RecentRecord]


class DashboardAnalytics(StrictRequest):
    range: AnalyticsRange
    period_start: datetime
    summary: DashboardSummary
    orders: OrderAnalytics
    payments: PaymentAnalytics
    inventory: InventoryAnalytics
    customers: CustomerAnalytics
    recent_activity: RecentActivity
