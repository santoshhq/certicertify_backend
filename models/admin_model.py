from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class AdminAccessLevel(str, Enum):
    Full = "full"
    Custom = "custom"


class AdminPermissions(BaseModel):
    students_view: bool = False
    students_create: bool = False
    students_update: bool = False
    students_delete: bool = False

    institutions_view: bool = False
    institutions_create: bool = False
    institutions_update: bool = False
    institutions_delete: bool = False


class Admin(BaseModel):
    admin_name: str = Field(...)
    email: EmailStr = Field(...)
    mobilenumber: str = Field(...)
    admin_userId: str = Field(..., min_length=8, max_length=8)
    password: str = Field(..., min_length=8)
    access_level: AdminAccessLevel = AdminAccessLevel.Custom
    permissions: AdminPermissions = Field(
        default_factory=AdminPermissions
    )


class UpdateAdmin(BaseModel):
    admin_name: Optional[str] = Field(default=None, min_length=1)
    email: Optional[EmailStr] = None
    mobilenumber: Optional[str] = Field(default=None, min_length=1)
    admin_userId: Optional[str] = Field(
        default=None,
        min_length=8,
        max_length=8
    )
    password: Optional[str] = Field(
        default=None,
        min_length=8
    )
    access_level: Optional[AdminAccessLevel] = None
    permissions: Optional[AdminPermissions] = None


class Login(BaseModel):
    admin_loginId: str = Field(...)
    password: str = Field(...)