from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from app.api.deps import DbSession,TenantContext,require_permission
from app.schemas.payment import PaymentPage,PaymentView,PaymentWrite,PaymentUpdate,Status
from app.services.payment_service import PaymentService
router=APIRouter(prefix='/payments',tags=['Payments'])
@router.get('',response_model=PaymentPage)
def list_payments(db:DbSession,ctx:Annotated[TenantContext,Depends(require_permission('payments.view'))],status:Status|None=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):return PaymentService(db,ctx).list(page,page_size,status)
@router.post('',response_model=PaymentView,status_code=201)
def create_payment(payload:PaymentWrite,db:DbSession,ctx:Annotated[TenantContext,Depends(require_permission('payments.create'))]):return PaymentService(db,ctx).create(payload)
@router.get('/{payment_id}',response_model=PaymentView)
def get_payment(payment_id:UUID,db:DbSession,ctx:Annotated[TenantContext,Depends(require_permission('payments.view'))]):return PaymentService(db,ctx).get(payment_id)
@router.patch('/{payment_id}',response_model=PaymentView)
def update_payment(payment_id:UUID,payload:PaymentUpdate,db:DbSession,ctx:Annotated[TenantContext,Depends(require_permission('payments.update'))]):return PaymentService(db,ctx).update(payment_id,payload)
