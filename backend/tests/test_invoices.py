from decimal import Decimal
from tests.test_customers import create as customer
from tests.test_inventory import adjust
from tests.test_orders import create as order
from tests.test_products import create as product
from tests.test_team import owner, team_client

def confirmed(client, headers, number='SO-INV'):
    cu=customer(client,headers); product_row=product(client,headers,name=f'Widget {number}',sku=f'SKU-{number}',barcode=f'BAR-{number}',selling_price='10.00',tax_rate='0');adjust(client,headers,product_row['id'],'opening_balance','10'); row=order(client,headers,cu['id'],product_row['id'],order_number=number); assert client.post(f"/api/v1/orders/{row['id']}/confirm",headers=headers).status_code==200; return row,cu,product_row
def invoice(client,headers,order_id): return client.post('/api/v1/invoices',headers=headers,json={'order_id':order_id})

def test_invoice_generation_snapshot_duplicate_and_payment_state(team_client):
 c=team_client; h,_=owner(c); row,cu,_=confirmed(c,h); made=invoice(c,h,row['id']); assert made.status_code==201,made.text; body=made.json()
 assert body['invoice_number']=='INV-000001' and body['grand_total']=='20.00' and body['customer_name']==cu['display_name'] and len(body['items'])==1 and body['payment_state']=='unpaid'
 assert invoice(c,h,row['id']).status_code==409
 paid=c.post('/api/v1/payments',headers=h,json={'order_id':row['id'],'payment_number':'INV-PAY','amount':'5.00','payment_method':'cash'});assert paid.status_code==201
 assert c.get(f"/api/v1/invoices/{body['id']}",headers=h).json()['payment_state']=='partially_paid'

def test_invoice_rejects_draft_and_tenant_access(team_client):
 c=team_client; h,_=owner(c); other,_=owner(c,'Beta');cu=customer(c,h);p=product(c,h,selling_price='10',tax_rate='0');draft=order(c,h,cu['id'],p['id'],order_number='SO-DRAFT')
 assert invoice(c,h,draft['id']).status_code==409
 row,_,_=confirmed(c,h,'SO-TENANT');made=invoice(c,h,row['id']).json();assert c.get(f"/api/v1/invoices/{made['id']}",headers=other).status_code==404;assert c.get('/api/v1/invoices',headers=other).json()['total']==0

def test_invoice_only_accepts_order_id_and_list_search(team_client):
 c=team_client;h,_=owner(c);row,_,_=confirmed(c,h,'SO-FILTER');r=c.post('/api/v1/invoices',headers=h,json={'order_id':row['id'],'grand_total':'999'});assert r.status_code==422
 made=invoice(c,h,row['id']);assert made.status_code==201
 listed=c.get('/api/v1/invoices?search=SO-FILTER',headers=h).json();assert listed['total']==1 and listed['items'][0]['order_number']=='SO-FILTER'
