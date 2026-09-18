from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os
load_dotenv()
# ---------------------------------------------------------
# Environment Configuration
# ---------------------------------------------------------

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE_DAYS = 7

if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY is not configured")


# ---------------------------------------------------------
# JWT Configuration
# ---------------------------------------------------------

security = HTTPBearer()


# ---------------------------------------------------------
# Create Access Token
# ---------------------------------------------------------

def create_access_token(
    user_id: str,
    role: str,
    organization_id: str | None = None,
    institution_id: str | None = None,
    email: str | None = None,
) -> str:

    expire = datetime.now(timezone.utc) + timedelta(
        days=ACCESS_TOKEN_EXPIRE_DAYS
    )

    payload = {
        "sub": user_id,
        "role": role,
        "organization_id": organization_id,
        "institution_id": institution_id,
        "email": email,
        "token_type": "access",
        "exp": expire
    }

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )


# ---------------------------------------------------------
# Verify Access Token
# ---------------------------------------------------------

def verify_access_token(token: str) -> dict:

    try:

        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        return payload

    except JWTError:

        raise ValueError("Invalid or expired token")


# ---------------------------------------------------------
# Get Current Authenticated Principal
# ---------------------------------------------------------

async def get_current_principal(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):

    token = credentials.credentials

    try:

        payload = verify_access_token(token)

    except ValueError:

        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    user_id = payload.get("sub")
    role = payload.get("role")

    if not user_id or not role:

        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials"
        )

    # Only an access token authenticates a request. Single-purpose tokens
    # (password reset, and anything added later) are signed with the same
    # key, so without this check one of them would work as a bearer
    # credential on every protected route.
    if payload.get("token_type") != "access":

        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials"
        )

    return payload


# ---------------------------------------------------------
# Get Current SuperAdmin
# ---------------------------------------------------------

async def get_current_superadmin(
    current_principal: dict = Depends(get_current_principal)
):

    if current_principal.get("role") != "superadmin":

        raise HTTPException(
            status_code=403,
            detail="Super Admin access required"
        )

    return current_principal


# ---------------------------------------------------------
# Get Current Admin
# ---------------------------------------------------------

async def get_current_admin(
    current_principal: dict = Depends(get_current_principal)
):

    if current_principal.get("role") != "admin":

        raise HTTPException(
            status_code=403,
            detail="Admin access required"
        )

    return current_principal

# ---------------------------------------------------------
# Password Reset Token
# ---------------------------------------------------------

PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = 10


def create_password_reset_token(
    user_id: str,
    role: str,
    email: str,
    otp_request_id: str
) -> str:
    """Mint a short lived, single purpose token for a password reset.

    Deliberately NOT an access token: it carries token_type
    "password_reset", expires in minutes rather than days, and is pinned to
    the exact OTP record that authorised it, so a reset token cannot be
    replayed against a different OTP and cannot be used as a bearer
    credential on protected routes.
    """

    expire = datetime.now(timezone.utc) + timedelta(
        minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": user_id,
        "role": role,
        "email": email,
        "otp_request_id": otp_request_id,
        "token_type": "password_reset",
        "exp": expire
    }

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )


def verify_password_reset_token(token: str, expected_role: str) -> dict:
    """Decode and validate a password reset token.

    Raises ValueError when the token is expired, tampered with, of the
    wrong type, or issued for a different role.
    """

    payload = verify_access_token(token)

    if payload.get("token_type") != "password_reset":
        raise ValueError("Invalid token type")

    if payload.get("role") != expected_role:
        raise ValueError("Invalid token role")

    if not payload.get("sub") or not payload.get("email"):
        raise ValueError("Malformed token payload")

    return payload
async def get_current_institution(
    current_principal: dict = Depends(get_current_principal)
):

    if current_principal.get("role") != "institution":

        raise HTTPException(
            status_code=403,
            detail="Super Admin access required"
        )

    return current_principal