from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import DbSession, TenantContext, require_permission
from app.schemas.product import ProductPage, ProductStatus, ProductSupplierView, ProductSupplierWrite, ProductView, ProductWrite
from app.services.product_service import ProductService

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("", response_model=ProductPage)
def list_products(db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("products.view"))],
                  search: str = Query("", max_length=160), status: ProductStatus | None = None,
                  category: str | None = Query(None, max_length=100), track_inventory: bool | None = None,
                  supplier_id: UUID | None = None,
                  sort_by: Literal["name", "sku", "category", "selling_price", "created_at", "updated_at"] = "created_at",
                  sort_direction: Literal["asc", "desc"] = "desc", page: int = Query(1, ge=1),
                  page_size: int = Query(20, ge=1, le=100)) -> ProductPage:
    return ProductService(db, ctx).list(search=search, status=status, category=category, track_inventory=track_inventory,
                                        supplier_id=supplier_id, sort_by=sort_by, sort_direction=sort_direction, page=page, size=page_size)


@router.post("", response_model=ProductView, status_code=201)
def create_product(payload: ProductWrite, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("products.create"))]) -> ProductView:
    return ProductService(db, ctx).create(payload)


@router.get("/{product_id}", response_model=ProductView)
def get_product(product_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("products.view"))]) -> ProductView:
    service = ProductService(db, ctx); return service.view(service.product(product_id))


@router.patch("/{product_id}", response_model=ProductView)
def update_product(product_id: UUID, payload: ProductWrite, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("products.update"))]) -> ProductView:
    return ProductService(db, ctx).update(product_id, payload)


@router.post("/{product_id}/activate", response_model=ProductView)
def activate_product(product_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("products.deactivate"))]) -> ProductView:
    return ProductService(db, ctx).status(product_id, True)


@router.post("/{product_id}/deactivate", response_model=ProductView)
def deactivate_product(product_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("products.deactivate"))]) -> ProductView:
    return ProductService(db, ctx).status(product_id, False)


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("products.delete"))]) -> Response:
    ProductService(db, ctx).status(product_id, False, delete=True); return Response(status_code=204)


@router.get("/{product_id}/suppliers", response_model=list[ProductSupplierView])
def product_suppliers(product_id: UUID, db: DbSession, ctx: Annotated[TenantContext, Depends(require_permission("products.view"))]) -> list[ProductSupplierView]:
    return ProductService(db, ctx).links(product_id)


@router.post("/{product_id}/suppliers", response_model=ProductSupplierView, status_code=201)
def add_product_supplier(product_id: UUID, payload: ProductSupplierWrite, db: DbSession,
                         ctx: Annotated[TenantContext, Depends(require_permission("products.manage_suppliers"))]) -> ProductSupplierView:
    return ProductService(db, ctx).add_supplier(product_id, payload)


@router.delete("/{product_id}/suppliers/{supplier_id}", status_code=204)
def remove_product_supplier(product_id: UUID, supplier_id: UUID, db: DbSession,
                            ctx: Annotated[TenantContext, Depends(require_permission("products.manage_suppliers"))]) -> Response:
    ProductService(db, ctx).remove_supplier(product_id, supplier_id); return Response(status_code=204)
