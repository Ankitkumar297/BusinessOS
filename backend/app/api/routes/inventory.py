from typing import Annotated
from uuid import UUID
from fastapi import APIRouter,Depends,Query
from app.api.deps import DbSession,TenantContext,require_permission
from app.schemas.inventory import Adjustment,InventoryView,InventoryPage,MovementView
from app.services.inventory_service import InventoryService
from app.models import Inventory,Product
router=APIRouter(prefix="/inventory",tags=["Inventory"])
@router.get("",response_model=InventoryPage)
def list_inventory(db:DbSession,ctx:Annotated[TenantContext,Depends(require_permission("inventory.view"))],search:str=Query("",max_length=160),status:str|None=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
 s=InventoryService(db,ctx); rows=[]
 for i in s.db.scalars(__import__('sqlalchemy').select(Inventory).join(Product).where(Inventory.business_id==ctx.business_id,Inventory.deleted_at.is_(None),Product.deleted_at.is_(None)).order_by(Inventory.updated_at.desc())).unique():
  v=s.view(i)
  if (not search or search.lower() in v.product_name.lower() or search.lower() in v.sku.lower()) and (not status or v.stock_status==status): rows.append(v)
 return InventoryPage(items=rows[(page-1)*page_size:page*page_size],total=len(rows),page=page,page_size=page_size)
@router.get("/{product_id}",response_model=InventoryView)
def get(product_id:UUID,db:DbSession,ctx:Annotated[TenantContext,Depends(require_permission("inventory.view"))]):return InventoryService(db,ctx).get(product_id)
@router.post("/{product_id}/adjust",response_model=InventoryView)
def adjust(product_id:UUID,payload:Adjustment,db:DbSession,ctx:Annotated[TenantContext,Depends(require_permission("inventory.adjust"))]):return InventoryService(db,ctx).adjust(product_id,payload)
@router.get("/{product_id}/movements",response_model=list[MovementView])
def movements(product_id:UUID,db:DbSession,ctx:Annotated[TenantContext,Depends(require_permission("inventory.view"))]):return InventoryService(db,ctx).movements(product_id)
