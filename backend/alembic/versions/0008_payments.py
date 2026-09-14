"""Payments ledger.
Revision ID: 0008_payments
Revises: 0007_orders
"""
from alembic import op
import sqlalchemy as sa
revision='0008_payments';down_revision='0007_orders';branch_labels=None;depends_on=None
def upgrade():
 op.create_table('payments',sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.text('CURRENT_TIMESTAMP'),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.text('CURRENT_TIMESTAMP'),nullable=False),sa.Column('deleted_at',sa.DateTime(timezone=True)),sa.Column('business_id',sa.Uuid(),sa.ForeignKey('businesses.id'),nullable=False),sa.Column('order_id',sa.Uuid(),nullable=False),sa.Column('payment_number',sa.String(64),nullable=False),sa.Column('amount',sa.Numeric(14,2),nullable=False),sa.Column('payment_method',sa.String(32),nullable=False),sa.Column('status',sa.String(16),server_default='completed',nullable=False),sa.Column('paid_at',sa.DateTime(timezone=True),nullable=False),sa.Column('external_reference',sa.String(160)),sa.Column('notes',sa.String(4000)),sa.ForeignKeyConstraint(['business_id','order_id'],['orders.business_id','orders.id']),sa.UniqueConstraint('business_id','payment_number',name='uq_payments_business_number'),sa.CheckConstraint('amount > 0',name='ck_payments_amount'),sa.CheckConstraint("payment_method IN ('cash','card','bank_transfer','upi','other')",name='ck_payments_method'),sa.CheckConstraint("status IN ('pending','completed','failed','cancelled')",name='ck_payments_status'))
 op.create_index('ix_payments_business_order','payments',['business_id','order_id']);op.create_index('ix_payments_business_date','payments',['business_id','paid_at'])
 if op.get_bind().dialect.name=='postgresql':
  op.execute("CREATE FUNCTION prevent_payment_tenant_move() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF OLD.business_id IS DISTINCT FROM NEW.business_id THEN RAISE EXCEPTION 'Payment tenant cannot be changed'; END IF; RETURN NEW; END $$");op.execute('CREATE TRIGGER payments_immutable_tenant BEFORE UPDATE OF business_id ON payments FOR EACH ROW EXECUTE FUNCTION prevent_payment_tenant_move()')
def downgrade():
 if op.get_bind().dialect.name=='postgresql':op.execute('DROP TRIGGER payments_immutable_tenant ON payments');op.execute('DROP FUNCTION prevent_payment_tenant_move()')
 op.drop_table('payments')
