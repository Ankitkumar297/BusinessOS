from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import DbSession, TenantContext, require_permission
from app.schemas.customer import CustomerPage, CustomerStatus, CustomerType, CustomerView, CustomerWrite
from app.services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=CustomerPage)
def list_customers(db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("customers.view"))],
                   search: str = Query("", max_length=160), status: CustomerStatus | None = None,
                   customer_type: CustomerType | None = None, sort_by: Literal["name", "created_at", "updated_at"] = "created_at",
                   sort_direction: Literal["asc", "desc"] = "desc", page: int = Query(1, ge=1),
                   page_size: int = Query(20, ge=1, le=100)) -> CustomerPage:
    return CustomerService(db, ctx).list(search, status, customer_type, sort_by, sort_direction, page, page_size)


@router.post("", response_model=CustomerView, status_code=201)
def create_customer(payload: CustomerWrite, db: DbSession,
                    ctx: Annotated[TenantContext, Depends(require_permission("customers.create"))]) -> CustomerView:
    return CustomerService(db, ctx).create(payload)


@router.get("/{customer_id}", response_model=CustomerView)
def get_customer(customer_id: UUID, db: DbSession,
                 ctx: Annotated[TenantContext, Depends(require_permission("customers.view"))]) -> CustomerView:
    return CustomerService(db, ctx).view(CustomerService(db, ctx).customer(customer_id))


@router.patch("/{customer_id}", response_model=CustomerView)
def update_customer(customer_id: UUID, payload: CustomerWrite, db: DbSession,
                    ctx: Annotated[TenantContext, Depends(require_permission("customers.update"))]) -> CustomerView:
    return CustomerService(db, ctx).update(customer_id, payload)


@router.post("/{customer_id}/activate", response_model=CustomerView)
def activate_customer(customer_id: UUID, db: DbSession,
                      ctx: Annotated[TenantContext, Depends(require_permission("customers.deactivate"))]) -> CustomerView:
    return CustomerService(db, ctx).status(customer_id, True)


@router.post("/{customer_id}/deactivate", response_model=CustomerView)
def deactivate_customer(customer_id: UUID, db: DbSession,
                        ctx: Annotated[TenantContext, Depends(require_permission("customers.deactivate"))]) -> CustomerView:
    return CustomerService(db, ctx).status(customer_id, False)


@router.delete("/{customer_id}", status_code=204)
def delete_customer(customer_id: UUID, db: DbSession,
                    ctx: Annotated[TenantContext, Depends(require_permission("customers.delete"))]) -> Response:
    CustomerService(db, ctx).status(customer_id, False, delete=True)
    return Response(status_code=204)
