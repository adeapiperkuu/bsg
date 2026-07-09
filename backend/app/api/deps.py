from typing import Annotated

from fastapi import Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser, get_current_user
from app.db.session import get_db_session

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
UserDep = Annotated[CurrentUser, Depends(get_current_user)]
LimitQuery = Annotated[int, Query(ge=1, le=100)]


async def require_explicit_user_action(
    user_action: Annotated[str | None, Header(alias="X-BSG-User-Action")] = None,
) -> None:
    if user_action != "true":
        raise ApiError(
            400,
            "USER_ACTION_REQUIRED",
            "AI work requires an explicit user action.",
        )


ExplicitUserActionDep = Annotated[None, Depends(require_explicit_user_action)]
