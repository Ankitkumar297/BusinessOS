from fastapi import APIRouter, HTTPException, status

from app.db.session import database_is_ready
from app.schemas.common import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health/live", response_model=HealthResponse)
def live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
def ready() -> HealthResponse:
    try:
        database_is_ready()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable") from exc
    return HealthResponse(status="ok")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")
