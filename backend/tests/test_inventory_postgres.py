import os
from uuid import UUID
import pytest
from threading import Barrier, Thread
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from tests.test_inventory import adjust
from tests.test_products import create as create_product
from tests.test_team import owner,team_client
from app.api.deps import TenantContext
from app.schemas.inventory import Adjustment
from app.services.inventory_service import InventoryService
from app.models import Inventory, StockMovement
pytestmark=pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),reason="PostgreSQL only")
def test_inventory_direct_tenant_immutability(team_client):
 c=team_client;a,ad=owner(c);b,bd=owner(c,"Beta");p=create_product(c,a,sku="PGI",barcode="PGI");adjust(c,a,p["id"],"opening_balance","10");inv=c.get(f"/api/v1/inventory/{p['id']}",headers=a).json();mov=c.get(f"/api/v1/inventory/{p['id']}/movements",headers=a).json()[0]
 with pytest.raises((IntegrityError, ProgrammingError)):
  with c.test_engine.begin() as x:x.execute(text("UPDATE inventories SET business_id=:b WHERE id=:i"),{"b":UUID(bd["business"]["id"]),"i":UUID(inv["id"])})
 with pytest.raises((IntegrityError, ProgrammingError)):
  with c.test_engine.begin() as x:x.execute(text("UPDATE stock_movements SET business_id=:b WHERE id=:i"),{"b":UUID(bd["business"]["id"]),"i":UUID(mov["id"])})

def test_postgres_concurrent_decreases_preserve_ledger(team_client):
 c=team_client; headers,data=owner(c); p=create_product(c,headers,sku="CON-A",barcode="CON-A");adjust(c,headers,p["id"],"opening_balance","10")
 from app.models import User
 with Session(c.test_engine) as s: actor=s.scalar(__import__('sqlalchemy').select(User).where(User.business_id==UUID(data["business"]["id"])))
 ctx=TenantContext(business_id=UUID(data["business"]["id"]),user_id=actor.id,permissions=frozenset({"inventory.adjust"})); gate=Barrier(2); results=[]
 def worker(q):
  s=Session(c.test_engine)
  try: gate.wait(); InventoryService(s,ctx).adjust(UUID(p["id"]),Adjustment(operation="decrease",quantity=Decimal(q),reason="concurrent"));results.append(True)
  finally: s.close()
 threads=[Thread(target=worker,args=(q,)) for q in ("3","4")]
 [t.start() for t in threads];[t.join() for t in threads]
 with Session(c.test_engine) as s:
  inv=s.scalar(__import__('sqlalchemy').select(Inventory).where(Inventory.product_id==UUID(p["id"]))); moves=list(s.scalars(__import__('sqlalchemy').select(StockMovement).where(StockMovement.inventory_id==inv.id,StockMovement.movement_type=="adjustment_out")))
  assert len(results)==2 and inv.quantity_on_hand==Decimal("3") and len(moves)==2 and sum(x.quantity_delta for x in moves)==Decimal("-7")

def test_postgres_concurrent_decreases_prevent_negative_stock(team_client):
 c=team_client;h,d=owner(c);p=create_product(c,h,sku="CON-B",barcode="CON-B");adjust(c,h,p["id"],"opening_balance","5")
 from app.models import User
 with Session(c.test_engine) as s:a=s.scalar(__import__('sqlalchemy').select(User).where(User.business_id==UUID(d["business"]["id"])))
 gate=Barrier(2); outcomes=[]
 def worker():
  s=Session(c.test_engine)
  try:
   gate.wait();InventoryService(s,TenantContext(business_id=UUID(d["business"]["id"]),user_id=a.id,permissions=frozenset({"inventory.adjust"}))).adjust(UUID(p["id"]),Adjustment(operation="decrease",quantity=Decimal("4"),reason="race"));outcomes.append("ok")
  except Exception: outcomes.append("failed");s.rollback()
  finally:s.close()
 ts=[Thread(target=worker) for _ in range(2)];[t.start() for t in ts];[t.join() for t in ts]
 with Session(c.test_engine) as s:
  inv=s.scalar(__import__('sqlalchemy').select(Inventory).where(Inventory.product_id==UUID(p["id"]))); moves=list(s.scalars(__import__('sqlalchemy').select(StockMovement).where(StockMovement.inventory_id==inv.id,StockMovement.movement_type=="adjustment_out")))
  assert outcomes.count("ok")==1 and outcomes.count("failed")==1 and inv.quantity_on_hand==Decimal("1") and len(moves)==1 and moves[0].quantity_delta==Decimal("-4")

def test_postgres_adjustment_rolls_back_when_movement_insert_fails(team_client,monkeypatch):
 c=team_client;h,d=owner(c);p=create_product(c,h,sku="ATOM-A",barcode="ATOM-A");adjust(c,h,p["id"],"opening_balance","10")
 from app.models import User
 with Session(c.test_engine) as s:a=s.scalar(__import__('sqlalchemy').select(User).where(User.business_id==UUID(d["business"]["id"])))
 ctx=TenantContext(business_id=UUID(d["business"]["id"]),user_id=a.id,permissions=frozenset({"inventory.adjust"})); s=Session(c.test_engine); original=s.add
 def fail(obj):
  if isinstance(obj,StockMovement):raise RuntimeError("forced movement failure")
  original(obj)
 monkeypatch.setattr(s,"add",fail)
 with pytest.raises(RuntimeError):InventoryService(s,ctx).adjust(UUID(p["id"]),Adjustment(operation="increase",quantity=Decimal("5"),reason="fault"))
 s.rollback();s.close()
 with Session(c.test_engine) as fresh:
  inv=fresh.scalar(__import__('sqlalchemy').select(Inventory).where(Inventory.product_id==UUID(p["id"])));assert inv.quantity_on_hand==Decimal("10")
  assert fresh.scalar(__import__('sqlalchemy').select(__import__('sqlalchemy').func.count()).select_from(StockMovement).where(StockMovement.inventory_id==inv.id,StockMovement.reason=="fault"))==0

def test_postgres_inventory_and_movement_rollback_on_outer_transaction_failure(team_client,monkeypatch):
 c=team_client;h,d=owner(c);p=create_product(c,h,sku="ATOM-B",barcode="ATOM-B");adjust(c,h,p["id"],"opening_balance","10")
 from app.models import User
 with Session(c.test_engine) as s:a=s.scalar(__import__('sqlalchemy').select(User).where(User.business_id==UUID(d["business"]["id"])))
 s=Session(c.test_engine);ctx=TenantContext(business_id=UUID(d["business"]["id"]),user_id=a.id,permissions=frozenset({"inventory.adjust"}));monkeypatch.setattr(s,"commit",lambda:(_ for _ in ()).throw(RuntimeError("forced outer failure")))
 with pytest.raises(RuntimeError):InventoryService(s,ctx).adjust(UUID(p["id"]),Adjustment(operation="decrease",quantity=Decimal("3"),reason="outer-fault"))
 s.rollback();s.close()
 with Session(c.test_engine) as fresh:
  inv=fresh.scalar(__import__('sqlalchemy').select(Inventory).where(Inventory.product_id==UUID(p["id"])));assert inv.quantity_on_hand==Decimal("10")
  assert fresh.scalar(__import__('sqlalchemy').select(__import__('sqlalchemy').func.count()).select_from(StockMovement).where(StockMovement.inventory_id==inv.id,StockMovement.reason=="outer-fault"))==0

def test_postgres_insufficient_stock_creates_no_partial_ledger(team_client):
 c=team_client;h,d=owner(c);p=create_product(c,h,sku="ATOM-C",barcode="ATOM-C");adjust(c,h,p["id"],"opening_balance","5")
 from app.models import User
 with Session(c.test_engine) as s:a=s.scalar(__import__('sqlalchemy').select(User).where(User.business_id==UUID(d["business"]["id"])))
 s=Session(c.test_engine);ctx=TenantContext(business_id=UUID(d["business"]["id"]),user_id=a.id,permissions=frozenset({"inventory.adjust"}))
 with pytest.raises(Exception):InventoryService(s,ctx).adjust(UUID(p["id"]),Adjustment(operation="decrease",quantity=Decimal("6"),reason="insufficient"))
 s.rollback();s.close()
 with Session(c.test_engine) as fresh:
  inv=fresh.scalar(__import__('sqlalchemy').select(Inventory).where(Inventory.product_id==UUID(p["id"])));assert inv.quantity_on_hand==Decimal("5")
  assert fresh.scalar(__import__('sqlalchemy').select(__import__('sqlalchemy').func.count()).select_from(StockMovement).where(StockMovement.inventory_id==inv.id,StockMovement.reason=="insufficient"))==0
