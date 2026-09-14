from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.schemas.team import StrictRequest

OrderStatus = Literal["draft", "confirmed", "cancelled"]
PaymentStatus = Literal["pending", "completed", "failed", "cancelled"]
PaymentMethod = Literal["cash", "card", "bank_transfer", "upi", "other"]
StockStatus = Literal["in_stock", "low_stock", "out_of_stock"]
CustomerStatus = Literal["active", "inactive"]


class OrderReportItem(StrictRequest):
    order_id: UUID
    order_number: str
    customer_id: UUID
    customer_name: str
    status: OrderStatus
    order_date: datetime
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal
    item_count: int


class OrderReportSummary(StrictRequest):
    matching_orders: int
    confirmed_order_count: int
    confirmed_order_value: Decimal


class OrderReport(StrictRequest):
    items: list[OrderReportItem]
    summary: OrderReportSummary
    total: int
    page: int
    page_size: int


class PaymentReportItem(StrictRequest):
    payment_id: UUID
    payment_number: str
    order_id: UUID
    order_number: str
    amount: Decimal
    payment_method: PaymentMethod
    status: PaymentStatus
    paid_at: datetime


class PaymentReportSummary(StrictRequest):
    matching_payments: int
    completed_count: int
    pending_count: int
    failed_count: int
    cancelled_count: int
    completed_amount: Decimal
    pending_amount: Decimal


class PaymentReport(StrictRequest):
    items: list[PaymentReportItem]
    summary: PaymentReportSummary
    total: int
    page: int
    page_size: int


class InventoryReportItem(StrictRequest):
    product_id: UUID
    product_name: str
    sku: str
    quantity: Decimal
    reorder_threshold: Decimal | None
    stock_status: StockStatus


class InventoryReportSummary(StrictRequest):
    tracked_products: int
    in_stock_count: int
    low_stock_count: int
    out_of_stock_count: int


class InventoryReport(StrictRequest):
    items: list[InventoryReportItem]
    summary: InventoryReportSummary
    total: int
    page: int
    page_size: int


class CustomerReportItem(StrictRequest):
    customer_id: UUID
    customer_name: str
    email: str | None
    phone: str | None
    status: CustomerStatus
    created_at: datetime
    order_count: int
    confirmed_order_value: Decimal


class CustomerReportSummary(StrictRequest):
    matching_customers: int
    active_count: int
    inactive_count: int
    confirmed_order_value: Decimal


class CustomerReport(StrictRequest):
    items: list[CustomerReportItem]
    summary: CustomerReportSummary
    total: int
    page: int
    page_size: int
