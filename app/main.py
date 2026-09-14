from fastapi import Depends, FastAPI

from app.api.auth import verify_api_key
from app.api.documentation import router as documentation_router
from app.api.exception_handlers import register_exception_handlers
from app.api.payments import router
from app.config import get_settings
from app.logging import setup_logging

settings = get_settings()
setup_logging(settings.log_level)
app = FastAPI(title="Payments Processing Service", version="0.1.0")
register_exception_handlers(app)
app.include_router(router)
app.include_router(documentation_router)


@app.get("/health", dependencies=[Depends(verify_api_key)], include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}
