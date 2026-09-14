import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.test_products import create
from tests.test_suppliers import create as create_supplier
from tests.test_team import owner, team_client

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="Run docker/compose.test.yml for PostgreSQL coverage")


def test_database_rejects_product_tenant_move_and_cross_tenant_link(team_client):
    client = team_client; first, _ = owner(client); second, second_data = owner(client, "Beta"); product = create(client, first); supplier = create_supplier(client, first)
    with pytest.raises(IntegrityError):
        with client.test_engine.begin() as connection:
            connection.execute(text("UPDATE products SET business_id=:business WHERE id=:product"), {"business": UUID(second_data["business"]["id"]), "product": UUID(product["id"])})
    with pytest.raises(IntegrityError):
        with client.test_engine.begin() as connection:
            connection.execute(text("INSERT INTO product_suppliers (id, business_id, product_id, supplier_id, is_primary, created_at, updated_at) VALUES (:id, :business, :product, :supplier, false, now(), now())"), {"id": uuid4(), "business": UUID(second_data["business"]["id"]), "product": UUID(product["id"]), "supplier": UUID(supplier["id"])})
