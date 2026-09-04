from fastapi import APIRouter

from progress_api.api.routes import auth, bim, captures, progress, projects, schedules, spatial

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(bim.router, prefix="/projects", tags=["bim"])
api_router.include_router(spatial.router, prefix="/projects", tags=["spatial"])
api_router.include_router(captures.router, prefix="/projects", tags=["captures"])
api_router.include_router(schedules.router, prefix="/projects", tags=["schedules"])
api_router.include_router(progress.router, prefix="/projects", tags=["progress"])
