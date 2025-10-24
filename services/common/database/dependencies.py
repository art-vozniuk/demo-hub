from typing import Annotated, AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session: AsyncSession = request.state.db
    try:
        yield session
    finally:
        pass


DbSession = Annotated[AsyncSession, Depends(get_db)]
