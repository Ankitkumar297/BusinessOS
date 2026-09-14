from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import Field
from app.schemas.team import StrictRequest
Method=Literal['cash','card','bank_transfer','upi','other']; Status=Literal['pending','completed','failed','cancelled']
class PaymentWrite(StrictRequest):
 order_id:UUID; payment_number:str=Field(min_length=1,max_length=64); amount:Decimal=Field(gt=0,max_digits=14,decimal_places=2); payment_method:Method; status:Status='completed'; paid_at:datetime|None=None; external_reference:str|None=Field(None,max_length=160); notes:str|None=Field(None,max_length=4000)
class PaymentView(PaymentWrite): id:UUID; business_id:UUID; paid_amount:Decimal; remaining_balance:Decimal; payment_state:Literal['unpaid','partially_paid','paid']; created_at:datetime; updated_at:datetime
class PaymentUpdate(StrictRequest):
 amount:Decimal|None=Field(None,gt=0,max_digits=14,decimal_places=2); payment_method:Method|None=None; status:Status|None=None; paid_at:datetime|None=None; external_reference:str|None=Field(None,max_length=160); notes:str|None=Field(None,max_length=4000)
class PaymentPage(StrictRequest): items:list[PaymentView]; total:int; page:int; page_size:int
