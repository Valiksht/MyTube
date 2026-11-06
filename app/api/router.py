from fastapi import APIRouter

from app.schemas.system import HealthResponse

router = APIRouter()


@router.get("/health", tags=["system"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
