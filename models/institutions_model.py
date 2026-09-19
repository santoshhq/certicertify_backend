from enum import Enum

from pydantic import BaseModel, Field, EmailStr


class InstitutionStatus(str, Enum):
    APPROVED = "Approved"
    PENDING = "Pending"
    SUSPENDED = "Suspended"


class Register(BaseModel):
    name: str = Field(..., min_length=1)
    email_id: EmailStr = Field(..., min_length=1)
    institution_name: str = Field(..., min_length=1)
    postal_code: str | None = None
    city: str = Field(..., min_length=1)
    state: str | None = None
    country: str = Field(..., min_length=1)
    mobile_no: str | None = None
    password: str = Field(..., min_length=8)
    superadmin_status: InstitutionStatus = InstitutionStatus.PENDING
    status:bool=Field(default=True)


class UpdateBase(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    email_id: EmailStr | None = Field(default=None, min_length=1)
    institution_name: str | None = Field(default=None, min_length=1)
    postal_code: str | None = None
    city: str | None = Field(default=None, min_length=1)
    state: str | None = None
    country: str | None = Field(default=None, min_length=1)
    mobile_no: str | None = None
    password: str | None = Field(default=None, min_length=8)
    superadmin_status: InstitutionStatus | None = None
    status: bool | None = None


class VerifyOTP(BaseModel):
    email_id: EmailStr
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class Login(BaseModel):
    email_id: EmailStr
    password: str = Field(min_length=8)


class PasswordResetRequest(BaseModel):
    email_id: EmailStr


class PasswordResetConfirm(BaseModel):
    email_id: EmailStr
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8)