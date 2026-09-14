from datetime import UTC,datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app.api.deps import TenantContext
from app.core.exceptions import AppError
from app.models import Order,Payment
from app.repositories.identity import UserRepository
from app.schemas.payment import PaymentPage,PaymentView,PaymentWrite
from app.schemas.payment import PaymentUpdate
from app.repositories.payments import PaymentRepository
from app.services.audit_service import AuditService
from app.services.auth_service import permissions_for
from app.services.team_events import TeamEvent,publish_team_event
class PaymentService:
 def __init__(self,db:Session,ctx:TenantContext):self.db,self.ctx=db,ctx
 def begin(self,p):
  self.db.execute(select(Order.id).where(Order.business_id==self.ctx.business_id).limit(1));a=UserRepository(self.db).by_id_with_access(self.ctx.business_id,self.ctx.user_id)
  if not a or p not in permissions_for(a):raise AppError(403,'You do not have permission to perform this action.')
 def order(self,id,lock=False):
  q=select(Order).where(Order.id==id,Order.business_id==self.ctx.business_id,Order.deleted_at.is_(None));q=q.with_for_update() if lock else q;o=self.db.scalar(q)
  if not o:raise AppError(404,'Order not found.')
  return o
 def summary(self,o):
  paid=self.db.scalar(select(func.coalesce(func.sum(Payment.amount),0)).where(Payment.order_id==o.id,Payment.business_id==self.ctx.business_id,Payment.status=='completed',Payment.deleted_at.is_(None))) or Decimal('0');remaining=o.grand_total-paid;state='paid' if remaining==0 else ('partially_paid' if paid else 'unpaid');return paid,remaining,state
 def view(self,p):
  paid,remaining,state=self.summary(p.order);return PaymentView.model_validate({**{k:getattr(p,k) for k in PaymentWrite.model_fields},'id':p.id,'business_id':p.business_id,'paid_amount':paid,'remaining_balance':remaining,'payment_state':state,'created_at':p.created_at,'updated_at':p.updated_at})
 def create(self,x:PaymentWrite):
  self.begin('payments.create');o=self.order(x.order_id,True)
  if o.status!='confirmed':raise AppError(409,'Payments require a confirmed order.')
  paid,remaining,_=self.summary(o)
  if x.status=='completed' and x.amount>remaining:raise AppError(409,'Payment exceeds remaining balance.')
  p=Payment(business_id=self.ctx.business_id,**x.model_dump(exclude={'paid_at'}),paid_at=x.paid_at or datetime.now(UTC));self.db.add(p);self.db.flush();AuditService(self.db,self.ctx).record(action='payment.created',entity_type='payment',entity_id=p.id,entity_display=p.payment_number,changed_fields=x.model_dump().keys());self.db.commit();publish_team_event(TeamEvent('payment.created',self.ctx.business_id,self.ctx.user_id,p.id));return self.view(p)
 def get(self,id):
  p=self.db.scalar(select(Payment).where(Payment.id==id,Payment.business_id==self.ctx.business_id,Payment.deleted_at.is_(None)))
  if not p:raise AppError(404,'Payment not found.')
  return self.view(p)
 def update(self,id,x:PaymentUpdate):
  self.begin('payments.update');p=PaymentRepository(self.db,self.ctx.business_id).payment(id)
  if not p:raise AppError(404,'Payment not found.')
  if p.status!='pending':raise AppError(409,'Only pending payments can be updated.')
  o=self.order(p.order_id,True);data=x.model_dump(exclude_unset=True);next_status=data.get('status',p.status);next_amount=data.get('amount',p.amount)
  if next_status not in ('pending','completed','failed','cancelled'):raise AppError(409,'Invalid payment status.')
  if next_status=='completed':
   paid=self.db.scalar(select(func.coalesce(func.sum(Payment.amount),0)).where(Payment.order_id==o.id,Payment.business_id==self.ctx.business_id,Payment.status=='completed',Payment.id!=p.id,Payment.deleted_at.is_(None))) or Decimal('0')
   if paid+next_amount>o.grand_total:raise AppError(409,'Payment exceeds remaining balance.')
  changed_fields=[k for k,v in data.items() if getattr(p,k)!=v]
  for k,v in data.items():setattr(p,k,v)
  self.db.flush();AuditService(self.db,self.ctx).record(action='payment.updated',entity_type='payment',entity_id=p.id,entity_display=p.payment_number,changed_fields=changed_fields);self.db.commit();publish_team_event(TeamEvent('payment.updated',self.ctx.business_id,self.ctx.user_id,p.id));return self.view(p)
 def list(self,page,size,status=None):
  q=select(Payment).where(Payment.business_id==self.ctx.business_id,Payment.deleted_at.is_(None));q=q.where(Payment.status==status) if status else q;total=self.db.scalar(select(func.count()).select_from(q.subquery())) or 0;return PaymentPage(items=[self.view(x) for x in self.db.scalars(q.order_by(Payment.paid_at.desc()).offset((page-1)*size).limit(size))],total=total,page=page,page_size=size)
