from fastapi import APIRouter

from app.api.routes.workforce import (
    dashboard,
    gaps,
    optimization,
    skills,
    summary,
    teams,
    training,
    utilization,
)

router = APIRouter(tags=["workforce"])
router.include_router(teams.router)
router.include_router(summary.router)
router.include_router(dashboard.router)
router.include_router(utilization.router)
router.include_router(skills.router)
router.include_router(training.router)
router.include_router(gaps.router)
router.include_router(optimization.router)
