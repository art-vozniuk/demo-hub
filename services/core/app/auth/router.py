import os
import logging
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from supabase import create_client, Client

log = logging.getLogger(__name__)

router = APIRouter()


class TestUserTokens(BaseModel):
    access_token: str
    refresh_token: str


def get_supabase_admin() -> Client:
    supabase_url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not service_role_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase configuration missing",
        )

    return create_client(supabase_url, service_role_key)


@router.post("/test-user", response_model=TestUserTokens)
async def sign_in_test_user():
    """Sign in as test user - for demo purposes only"""
    test_email = os.getenv("TEST_USER_EMAIL")
    test_password = os.getenv("TEST_USER_PASSWORD")

    if not test_email or not test_password:
        log.error("Test user credentials not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Test user sign-in not available",
        )

    try:
        supabase = get_supabase_admin()

        response = supabase.auth.sign_in_with_password(
            {"email": test_email, "password": test_password}
        )

        if not response.session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to sign in test user",
            )

        log.info(f"Test user signed in: {test_email}")

        return TestUserTokens(
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
        )

    except Exception as e:
        log.error(f"Test user sign-in failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Test user sign-in failed: {str(e)}",
        )
