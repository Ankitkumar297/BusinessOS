"""Post-commit integration boundary; delivery providers can subscribe later.

Events are logged today. They are not a durable notification queue or audit store.
"""
from dataclasses import dataclass
import logging
from uuid import UUID

logger = logging.getLogger("businessos.team.events")


@dataclass(frozen=True)
class TeamEvent:
    name: str
    business_id: UUID
    actor_id: UUID
    entity_id: UUID


def publish_team_event(event: TeamEvent) -> None:
    """Publish a committed event to the currently configured logging sink."""
    logger.info("%s business_id=%s actor_id=%s entity_id=%s", event.name,
                event.business_id, event.actor_id, event.entity_id)
