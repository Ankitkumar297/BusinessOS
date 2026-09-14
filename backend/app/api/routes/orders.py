from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, TenantContext, require_permission
from app.schemas.order import OrderPage, OrderStatus, OrderView, OrderWrite
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["Orders"])

@router.get("", response_model=OrderPage)
def list_orders(db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("orders.view"))], search: str = Query("", max_length=160), status: OrderStatus | None = None, sort_by: Literal["order_number", "order_date", "created_at", "updated_at", "grand_total"] = "created_at", sort_direction: Literal["asc", "desc"] = "desc", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)) -> OrderPage:
    return OrderService(db, ctx).list(search=search, status=status, sort_by=sort_by, sort_direction=sort_direction, page=page, size=page_size)

@router.post("", response_model=OrderView, status_code=201)
def create_order(payload: OrderWrite, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("orders.create"))]) -> OrderView:
    return OrderService(db, ctx).create(payload)

@router.get("/{order_id}", response_model=OrderView)
def get_order(order_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("orders.view"))]) -> OrderView:
    return OrderService(db, ctx).view(OrderService(db, ctx).order(order_id))

@router.patch("/{order_id}", response_model=OrderView)
def update_order(order_id: UUID, payload: OrderWrite, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("orders.update"))]) -> OrderView:
    return OrderService(db, ctx).update(order_id, payload)

@router.post("/{order_id}/confirm", response_model=OrderView)
def confirm_order(order_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("orders.confirm"))]) -> OrderView:
    return OrderService(db, ctx).confirm(order_id)

@router.post("/{order_id}/cancel", response_model=OrderView)
def cancel_order(order_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("orders.cancel"))]) -> OrderView:
    return OrderService(db, ctx).cancel(order_id)
