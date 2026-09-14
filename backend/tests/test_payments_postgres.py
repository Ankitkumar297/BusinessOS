import os
from decimal import Decimal
from threading import Barrier, Thread
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.models import Order, Payment, User
from app.schemas.payment import PaymentUpdate, PaymentWrite
from app.services.payment_service import PaymentService
from tests.test_customers import create as create_customer
from tests.test_inventory import adjust
from tests.test_orders import create as create_order
from tests.test_products import create as create_product
from tests.test_team import owner, team_client


pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL only"
)


def confirmed_order(client, headers, *, price="50.00"):
    customer = create_customer(client, headers)
    product = create_product(client, headers, selling_price=price, tax_rate="0")
    adjust(client, headers, product["id"], "opening_balance", "10")
    order = create_order(client, headers, customer["id"], product["id"])
    response = client.post(f"/api/v1/orders/{order['id']}/confirm", headers=headers)
    assert response.status_code == 200, response.text
    return order


def payment_context(client, business_id):
    with Session(client.test_engine) as session:
        actor = session.scalar(select(User).where(User.business_id == UUID(business_id)))
        return TenantContext(
            business_id=UUID(business_id),
            user_id=actor.id,
            permissions=frozenset({"payments.create", "payments.update"}),
        )


def payment_write(order_id, number, amount, status="completed"):
    return PaymentWrite(
        order_id=UUID(order_id),
        payment_number=number,
        amount=Decimal(amount),
        payment_method="cash",
        status=status,
    )


def test_postgres_concurrent_completed_payments_do_not_overpay(team_client):
    client = team_client
    headers, registration = owner(client)
    order = confirmed_order(client, headers)
    context = payment_context(client, registration["business"]["id"])
    gate, outcomes = Barrier(2), []

    def worker(number):
        session = Session(client.test_engine)
        try:
            gate.wait()
            PaymentService(session, context).create(payment_write(order["id"], number, "60.00"))
            outcomes.append("completed")
        except Exception:
            session.rollback()
            outcomes.append("rejected")
        finally:
            session.close()

    threads = [Thread(target=worker, args=(number,)) for number in ("PG-RACE-1", "PG-RACE-2")]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]

    with Session(client.test_engine) as fresh:
        paid = fresh.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.order_id == UUID(order["id"]), Payment.status == "completed"
            )
        )
        rows = list(fresh.scalars(select(Payment).where(Payment.order_id == UUID(order["id"]))))
        grand_total = fresh.scalar(select(Order.grand_total).where(Order.id == UUID(order["id"])))
        assert outcomes.count("completed") == 1
        assert outcomes.count("rejected") == 1
        assert paid == Decimal("60.00")
        assert paid <= grand_total == Decimal("100.00")
        assert len(rows) == 1


def test_postgres_concurrent_pending_payment_completion_does_not_overpay(team_client):
    client = team_client
    headers, registration = owner(client)
    order = confirmed_order(client, headers)
    context = payment_context(client, registration["business"]["id"])
    pending_ids = []
    for number in ("PG-PENDING-1", "PG-PENDING-2"):
        session = Session(client.test_engine)
        try:
            pending_ids.append(
                PaymentService(session, context)
                .create(payment_write(order["id"], number, "60.00", "pending"))
                .id
            )
        finally:
            session.close()

    gate, outcomes = Barrier(2), []

    def worker(payment_id):
        session = Session(client.test_engine)
        try:
            gate.wait()
            PaymentService(session, context).update(payment_id, PaymentUpdate(status="completed"))
            outcomes.append("completed")
        except Exception:
            session.rollback()
            outcomes.append("rejected")
        finally:
            session.close()

    threads = [Thread(target=worker, args=(payment_id,)) for payment_id in pending_ids]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]

    with Session(client.test_engine) as fresh:
        payments = list(fresh.scalars(select(Payment).where(Payment.order_id == UUID(order["id"]))))
        paid = sum((payment.amount for payment in payments if payment.status == "completed"), Decimal("0"))
        grand_total = fresh.scalar(select(Order.grand_total).where(Order.id == UUID(order["id"])))
        assert outcomes.count("completed") == 1
        assert outcomes.count("rejected") == 1
        assert paid == Decimal("60.00")
        assert paid <= grand_total == Decimal("100.00")
        assert sum(payment.status == "pending" for payment in payments) == 1


def test_postgres_payment_create_rolls_back_after_locked_validation_failure(team_client, monkeypatch):
    client = team_client
    headers, registration = owner(client)
    order = confirmed_order(client, headers)
    context = payment_context(client, registration["business"]["id"])
    session = Session(client.test_engine)
    monkeypatch.setattr(
        session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("forced pre-commit failure"))
    )
    with pytest.raises(RuntimeError, match="forced pre-commit failure"):
        PaymentService(session, context).create(payment_write(order["id"], "PG-ATOMIC", "20.00"))
    session.rollback()
    session.close()

    with Session(client.test_engine) as fresh:
        assert fresh.scalar(
            select(func.count()).select_from(Payment).where(
                Payment.order_id == UUID(order["id"]), Payment.payment_number == "PG-ATOMIC"
            )
        ) == 0
        assert fresh.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.order_id == UUID(order["id"]), Payment.status == "completed"
            )
        ) == Decimal("0")
        assert fresh.scalar(select(Order.grand_total).where(Order.id == UUID(order["id"]))) == Decimal("100.00")


def test_postgres_payment_tenant_trigger_and_composite_order_fk(team_client):
    client = team_client
    headers, registration = owner(client)
    other_headers, other_registration = owner(client, "Beta")
    order = confirmed_order(client, headers)
    payment_response = client.post(
        "/api/v1/payments",
        headers=headers,
        json={
            "order_id": order["id"], "payment_number": "PG-TENANT", "amount": "10.00",
            "payment_method": "cash", "status": "completed",
        },
    )
    assert payment_response.status_code == 201, payment_response.text
    payment_id = UUID(payment_response.json()["id"])
    own_business = UUID(registration["business"]["id"])
    other_business = UUID(other_registration["business"]["id"])

    with pytest.raises(ProgrammingError):
        with client.test_engine.begin() as connection:
            connection.execute(
                text("UPDATE payments SET business_id=:business_id WHERE id=:payment_id"),
                {"business_id": other_business, "payment_id": payment_id},
            )
    with Session(client.test_engine) as fresh:
        assert fresh.scalar(select(Payment.business_id).where(Payment.id == payment_id)) == own_business

    with pytest.raises(IntegrityError):
        with client.test_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO payments "
                    "(id, business_id, order_id, payment_number, amount, payment_method, status, paid_at, created_at, updated_at) "
                    "VALUES (:id, :business_id, :order_id, :payment_number, :amount, 'cash', 'completed', now(), now(), now())"
                ),
                {
                    "id": uuid4(), "business_id": other_business, "order_id": UUID(order["id"]),
                    "payment_number": "PG-CROSS-TENANT", "amount": Decimal("1.00"),
                },
            )


def test_postgres_payment_migration_has_tenant_integrity_structures(team_client):
    with team_client.test_engine.connect() as connection:
        columns = {
            row[0]
            for row in connection.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name='payments'")
            )
        }
        constraints = " ".join(
            row[0] for row in connection.execute(
                text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='payments'::regclass")
            )
        )
        types = {
            row[0]: row[1]
            for row in connection.execute(
                text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='payments'")
            )
        }
        indexes = {
            row[0] for row in connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename='payments'")
            )
        }
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        trigger = connection.scalar(
            text("SELECT 1 FROM pg_trigger WHERE tgrelid='payments'::regclass AND tgname='payments_immutable_tenant' AND NOT tgisinternal")
        )
    assert {"id", "business_id", "order_id", "payment_number", "amount", "status"} <= columns
    assert types["amount"] == "numeric"
    assert "FOREIGN KEY (business_id, order_id) REFERENCES orders(business_id, id)" in constraints
    assert {"ix_payments_business_order", "ix_payments_business_date"} <= indexes
    assert trigger == 1
    # The payments structures remain valid at the application migration head.
    assert revision == "0011_permission_backfill"
