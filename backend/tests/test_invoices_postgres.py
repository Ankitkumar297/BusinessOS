import os
from threading import Barrier, Thread
from uuid import UUID, uuid4
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from app.api.deps import TenantContext
from app.models import Invoice, InvoiceItem, User
from app.schemas.invoice import InvoiceWrite
from app.services.invoice_service import InvoiceService
from tests.test_invoices import confirmed
from tests.test_team import owner, team_client
pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='PostgreSQL only')
def ctx(client,business):
 with Session(client.test_engine) as s:
  user=s.scalar(select(User).where(User.business_id==UUID(business)))
  return TenantContext(business_id=UUID(business),user_id=user.id,permissions=frozenset({'invoices.create','invoices.view'}))
def test_postgres_concurrent_invoice_singleton_and_numbering(team_client):
 c=team_client;h,r=owner(c); one,_,_=confirmed(c,h,'SO-PG-ONE');two,_,_=confirmed(c,h,'SO-PG-TWO');context=ctx(c,r['business']['id']);gate=Barrier(2);out=[]
 def worker(order_id):
  s=Session(c.test_engine)
  try: gate.wait();out.append(InvoiceService(s,context).create(InvoiceWrite(order_id=UUID(order_id))).invoice_number)
  except Exception: s.rollback();out.append('failed')
  finally:s.close()
 ts=[Thread(target=worker,args=(x['id'],)) for x in (one,two)];[t.start() for t in ts];[t.join() for t in ts]
 with Session(c.test_engine) as fresh:
  rows=list(fresh.scalars(select(Invoice).where(Invoice.business_id==context.business_id)))
  assert len(rows)==2 and len({x.invoice_number for x in rows})==2 and 'failed' not in out
def test_postgres_invoice_tenant_fk_and_immutability(team_client):
 c=team_client;h,r=owner(c);_,other=owner(c,'Beta');row,_,_=confirmed(c,h,'SO-PG-TENANT');made=c.post('/api/v1/invoices',headers=h,json={'order_id':row['id']});assert made.status_code==201,made.text;invoice_id=UUID(made.json()['id'])
 with pytest.raises(ProgrammingError):
  with c.test_engine.begin() as x:x.execute(text('UPDATE invoices SET business_id=:business WHERE id=:id'),{'business':UUID(other['business']['id']),'id':invoice_id})
 with pytest.raises(IntegrityError):
  with c.test_engine.begin() as x:x.execute(text("INSERT INTO invoices (id,business_id,order_id,invoice_number,status,issued_at,order_number,customer_name,subtotal,tax_total,grand_total,created_at,updated_at) VALUES (:id,:business,:order,'INV-X','issued',now(),'X','X',0,0,0,now(),now())"),{'id':uuid4(),'business':UUID(other['business']['id']),'order':UUID(row['id'])})
def test_postgres_invoice_item_failure_rolls_back(team_client,monkeypatch):
 c=team_client;h,r=owner(c);row,_,_=confirmed(c,h,'SO-PG-ATOMIC');context=ctx(c,r['business']['id']);s=Session(c.test_engine)
 monkeypatch.setattr(s,'flush',lambda: (_ for _ in ()).throw(RuntimeError('forced item failure')))
 with pytest.raises(RuntimeError): InvoiceService(s,context).create(InvoiceWrite(order_id=UUID(row['id'])))
 s.rollback();s.close()
 with Session(c.test_engine) as fresh: assert fresh.scalar(select(func.count()).select_from(Invoice).where(Invoice.order_id==UUID(row['id'])))==0
