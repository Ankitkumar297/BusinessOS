import os
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.test_customers import create
from tests.test_team import owner, team_client

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="Run docker/compose.test.yml for PostgreSQL coverage")


def test_database_rejects_customer_tenant_move(team_client):
    client = team_client; first, first_data = owner(client); second, second_data = owner(client, "Beta")
    customer = create(client, first)
    with pytest.raises(IntegrityError):
        with client.test_engine.begin() as connection:
            connection.execute(text("UPDATE customers SET business_id=:business WHERE id=:customer"), {
                "business": UUID(second_data["business"]["id"]), "customer": UUID(customer["id"]),
            })
    assert client.get(f"/api/v1/customers/{customer['id']}", headers=second).status_code == 404
