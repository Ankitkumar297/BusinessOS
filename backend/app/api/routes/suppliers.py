from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import DbSession, TenantContext, require_permission
from app.schemas.supplier import SupplierPage, SupplierStatus, SupplierView, SupplierWrite
from app.services.supplier_service import SupplierService

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


@router.get("", response_model=SupplierPage)
def list_suppliers(db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("suppliers.view"))],
                   search: str = Query("", max_length=160), status: SupplierStatus | None = None,
                   country: str | None = Query(None, max_length=100),
                   sort_by: Literal["name", "supplier_code", "created_at", "updated_at"] = "created_at",
                   sort_direction: Literal["asc", "desc"] = "desc", page: int = Query(1, ge=1),
                   page_size: int = Query(20, ge=1, le=100)) -> SupplierPage:
    return SupplierService(db, ctx).list(search, status, country, sort_by, sort_direction, page, page_size)


@router.post("", response_model=SupplierView, status_code=201)
def create_supplier(payload: SupplierWrite, db: DbSession,
                    ctx: Annotated[TenantContext, Depends(require_permission("suppliers.create"))]) -> SupplierView:
    return SupplierService(db, ctx).create(payload)


@router.get("/{supplier_id}", response_model=SupplierView)
def get_supplier(supplier_id: UUID, db: DbSession,
                 ctx: Annotated[TenantContext, Depends(require_permission("suppliers.view"))]) -> SupplierView:
    return SupplierService(db, ctx).view(SupplierService(db, ctx).supplier(supplier_id))


@router.patch("/{supplier_id}", response_model=SupplierView)
def update_supplier(supplier_id: UUID, payload: SupplierWrite, db: DbSession,
                    ctx: Annotated[TenantContext, Depends(require_permission("suppliers.update"))]) -> SupplierView:
    return SupplierService(db, ctx).update(supplier_id, payload)


@router.post("/{supplier_id}/activate", response_model=SupplierView)
def activate_supplier(supplier_id: UUID, db: DbSession,
                      ctx: Annotated[TenantContext, Depends(require_permission("suppliers.deactivate"))]) -> SupplierView:
    return SupplierService(db, ctx).status(supplier_id, True)


@router.post("/{supplier_id}/deactivate", response_model=SupplierView)
def deactivate_supplier(supplier_id: UUID, db: DbSession,
                        ctx: Annotated[TenantContext, Depends(require_permission("suppliers.deactivate"))]) -> SupplierView:
    return SupplierService(db, ctx).status(supplier_id, False)


@router.delete("/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: UUID, db: DbSession,
                    ctx: Annotated[TenantContext, Depends(require_permission("suppliers.delete"))]) -> Response:
    SupplierService(db, ctx).status(supplier_id, False, delete=True)
    return Response(status_code=204)
