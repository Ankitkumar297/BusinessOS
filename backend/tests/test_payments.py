from tests.test_customers import create as customer
from tests.test_inventory import adjust
from tests.test_orders import create as order
from tests.test_products import create as product
from tests.test_team import owner,team_client

def payment(c,h,order_id,number='PAY-1',amount='5.00',status='completed'):
 return c.post('/api/v1/payments',headers=h,json={'order_id':order_id,'payment_number':number,'amount':amount,'payment_method':'cash','status':status})
def confirmed(c,h,total='10.00'):
 cu=customer(c,h);p=product(c,h,selling_price=total,tax_rate='0');adjust(c,h,p['id'],'opening_balance','10');o=order(c,h,cu['id'],p['id']);assert c.post(f"/api/v1/orders/{o['id']}/confirm",headers=h).status_code==200;return o
def test_payment_balances_lifecycle_and_tenant_scope(team_client):
 c=team_client;a,_=owner(c);b,_=owner(c,'Beta');o=confirmed(c,a)
 first=payment(c,a,o['id'],'PAY-1','4.00');assert first.status_code==201 and first.json()['payment_state']=='partially_paid' and first.json()['remaining_balance']=='16.00'
 second=payment(c,a,o['id'],'PAY-2','16.00');assert second.status_code==201 and second.json()['payment_state']=='paid'
 assert payment(c,a,o['id'],'PAY-3','0').status_code==422
 assert payment(c,a,o['id'],'PAY-3','1.00').status_code==409
 assert c.get(f"/api/v1/payments/{first.json()['id']}",headers=b).status_code==404
 assert c.get('/api/v1/payments',headers=a).json()['total']==2
 pending=payment(c,a,o['id'],'PAY-P','1.00','pending');assert pending.status_code==201
 assert c.patch(f"/api/v1/payments/{pending.json()['id']}",headers=a,json={'notes':'received'}).status_code==200
 assert c.patch(f"/api/v1/payments/{first.json()['id']}",headers=a,json={'amount':'3.00'}).status_code==409
