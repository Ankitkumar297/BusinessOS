from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Payment
class PaymentRepository:
 def __init__(self,db:Session,business_id:UUID):self.db,self.business_id=db,business_id
 def payment(self,id:UUID):return self.db.scalar(select(Payment).where(Payment.id==id,Payment.business_id==self.business_id,Payment.deleted_at.is_(None)))
