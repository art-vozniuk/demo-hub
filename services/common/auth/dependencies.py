import logging
from typing import Optional, Callable
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .jwks import verify_jwt_with_jwks
from .models import User

log = logging.getLogger(__name__)

security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)


def create_get_current_user(supabase_url: str) -> Callable:
    async def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> User:
        token = credentials.credentials
        payload = await verify_jwt_with_jwks(token, supabase_url)

        user_id = payload.get("sub")
        email = payload.get("email")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )

        return User(id=user_id, email=email, metadata=payload)

    return get_current_user


def create_get_current_user_optional(supabase_url: str) -> Callable:
    async def get_current_user_optional(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(
            security_optional
        ),
    ) -> Optional[User]:
        if not credentials:
            return None

        try:
            token = credentials.credentials
            payload = await verify_jwt_with_jwks(token, supabase_url)

            user_id = payload.get("sub")
            email = payload.get("email")

            return User(id=user_id, email=email, metadata=payload) if user_id else None
        except HTTPException:
            return None

    return get_current_user_optional
