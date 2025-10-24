import logging
from typing import Optional
import jwt
from jwt import PyJWKClient, PyJWKClientError
from fastapi import HTTPException, status

log = logging.getLogger(__name__)

_jwk_client: Optional[PyJWKClient] = None
_jwks_url: Optional[str] = None


def get_jwk_client(supabase_url: str) -> PyJWKClient:
    global _jwk_client, _jwks_url

    jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json"

    if _jwk_client is None or _jwks_url != jwks_url:
        log.info(f"Initializing PyJWKClient with {jwks_url}")
        _jwk_client = PyJWKClient(
            jwks_url,
            cache_keys=True,
            max_cached_keys=16,
            cache_jwk_set=True,
            lifespan=3600,
        )
        _jwks_url = jwks_url

    return _jwk_client


async def verify_jwt_with_jwks(token: str, supabase_url: str) -> dict:
    try:
        jwk_client = get_jwk_client(supabase_url)

        signing_key = jwk_client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            options={
                "verify_signature": True,
                "verify_aud": False,
                "verify_exp": True,
            },
        )

        return payload
    except PyJWKClientError as e:
        log.error(f"JWKS client error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.ExpiredSignatureError as e:
        log.error(f"Token expired: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        log.error(f"JWT verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
