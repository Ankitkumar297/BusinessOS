from decimal import Decimal
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.models import Business, Inventory, Product, StockMovement
from app.repositories.identity import UserRepository
from app.schemas.inventory import Adjustment, InventoryView, MovementView
from app.services.audit_service import AuditService
from app.services.auth_service import permissions_for
from app.services.team_events import TeamEvent, publish_team_event
class InventoryService:
 def __init__(self, db: Session, ctx: TenantContext): self.db,self.ctx=db,ctx
 def begin(self,p:str|None):
  self.db.execute(select(Business.id).where(Business.id==self.ctx.business_id).with_for_update()).one(); self.db.expire_all(); a=UserRepository(self.db).by_id_with_access(self.ctx.business_id,self.ctx.user_id)
  if not a or (p is not None and p not in permissions_for(a)): raise AppError(403,"You do not have permission to perform this action.")
 def inventory(self,pid:UUID,lock=False):
  q=select(Inventory).where(Inventory.business_id==self.ctx.business_id,Inventory.product_id==pid,Inventory.deleted_at.is_(None))
  if lock:q=q.with_for_update()
  return self.db.scalar(q)
 def product(self,pid):
  p=self.db.scalar(select(Product).where(Product.id==pid,Product.business_id==self.ctx.business_id,Product.deleted_at.is_(None)))
  if not p:raise AppError(404,"Product not found.")
  return p
 def view(self,i):
  level=i.product.reorder_level; q=i.quantity_on_hand; status="out_of_stock" if q==0 else ("low_stock" if level is not None and q<=level else "in_stock")
  return InventoryView(id=i.id,product_id=i.product_id,product_name=i.product.name,sku=i.product.sku,unit_of_measure=i.product.unit_of_measure,quantity_on_hand=q,reorder_level=level,stock_status=status,updated_at=i.updated_at)
 def get(self,pid):
  i=self.inventory(pid); 
  if not i: raise AppError(404,"Inventory not found.")
  return self.view(i)
 def adjust(self,pid:UUID,x:Adjustment,commit:bool=True,permission:str|None="inventory.adjust"):
  self.begin(permission); p=self.product(pid)
  if not p.track_inventory or p.status!="active":raise AppError(409,"This product cannot be adjusted.")
  i=self.inventory(pid,True)
  if not i: i=Inventory(business_id=self.ctx.business_id,product_id=pid,quantity_on_hand=Decimal("0"));self.db.add(i);self.db.flush();self.db.refresh(i,["product"])
  before=i.quantity_on_hand; after=x.quantity if x.operation=="correction" else before+ (x.quantity if x.operation in ("opening_balance","increase") else -x.quantity)
  if after<0:raise AppError(409,"Stock cannot fall below zero.")
  old="out_of_stock" if before==0 else ("low_stock" if p.reorder_level is not None and before<=p.reorder_level else "in_stock");typ={"increase":"adjustment_in","decrease":"adjustment_out"}.get(x.operation,x.operation); i.quantity_on_hand=after; m=StockMovement(business_id=self.ctx.business_id,inventory_id=i.id,product_id=pid,movement_type=typ,quantity_delta=after-before,quantity_before=before,quantity_after=after,reason=x.reason,notes=x.notes,actor_user_id=self.ctx.user_id);self.db.add(m);self.db.flush();new="out_of_stock" if after==0 else ("low_stock" if p.reorder_level is not None and after<=p.reorder_level else "in_stock");
  if commit:
   AuditService(self.db,self.ctx).record(action="inventory.adjusted",entity_type="inventory",entity_id=i.id,entity_display=p.name,changed_fields=["quantity_on_hand"])
   self.db.commit();publish_team_event(TeamEvent("inventory.adjusted",self.ctx.business_id,self.ctx.user_id,m.id));
  if commit and new=="out_of_stock" and old!="out_of_stock":publish_team_event(TeamEvent("inventory.out_of_stock",self.ctx.business_id,self.ctx.user_id,m.id))
  elif commit and new=="low_stock" and old=="in_stock":publish_team_event(TeamEvent("inventory.low_stock",self.ctx.business_id,self.ctx.user_id,m.id))
  elif commit and new=="in_stock" and old in ("low_stock","out_of_stock"):publish_team_event(TeamEvent("inventory.stock_restored",self.ctx.business_id,self.ctx.user_id,m.id))
  return self.view(i)
 def movements(self,pid):
  i=self.inventory(pid); 
  if not i:raise AppError(404,"Inventory not found.")
  return [MovementView.model_validate(x,from_attributes=True) for x in self.db.scalars(select(StockMovement).where(StockMovement.inventory_id==i.id).order_by(StockMovement.created_at.desc()).limit(100))]
