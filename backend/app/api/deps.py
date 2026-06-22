from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, get_current_user
from app.db.session import get_db_session

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
UserDep = Annotated[CurrentUser, Depends(get_current_user)]
LimitQuery = Annotated[int, Query(ge=1, le=100)]
