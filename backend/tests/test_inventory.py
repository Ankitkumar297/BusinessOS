from tests.test_products import create as create_product,payload
from tests.test_team import owner,team_client
from tests.test_suppliers import create as create_supplier

def adjust(c,h,p,op,q): return c.post(f"/api/v1/inventory/{p}/adjust",headers=h,json={"operation":op,"quantity":q,"reason":"test"})
def test_inventory_lifecycle_tenant_and_ledger(team_client):
 c=team_client; a,_=owner(c); b,_=owner(c,"Beta"); p=create_product(c,a,reorder_level="10",sku="I-1",barcode="I1")
 assert adjust(c,a,p["id"],"opening_balance","20").status_code==200
 assert adjust(c,a,p["id"],"decrease","12").json()["quantity_on_hand"]=="8.000"
 moves=c.get(f"/api/v1/inventory/{p['id']}/movements",headers=a).json();assert len(moves)==2 and {x["quantity_after"] for x in moves}=={"20.000","8.000"}
 assert c.get(f"/api/v1/inventory/{p['id']}",headers=b).status_code==404
 assert adjust(c,b,p["id"],"increase","1").status_code==404
 assert c.get(f"/api/v1/inventory/{p['id']}/movements",headers=b).status_code==404
 assert adjust(c,a,p["id"],"decrease","99").status_code==409
 non=create_product(c,a,sku="N-1",barcode="N1",track_inventory=False);assert adjust(c,a,non["id"],"increase","1").status_code==409
 assert c.get("/api/v1/inventory?search=Widget",headers=a).status_code==200
