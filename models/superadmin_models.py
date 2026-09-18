from pydantic import BaseModel,Field,EmailStr
from typing import Optional

class SuperAdmin(BaseModel):
    fullname:str=Field(...,)
    email:EmailStr=Field(...,)
    mobilenumber:str=Field(...,)
    password:str=Field(...,)
    
class UpdateSuperAdmin(BaseModel):
    fullname:Optional[str]=Field(default=None)
    email:Optional[EmailStr]=Field(default=None)
    mobilenumber:Optional[str]=Field(default=None)
    password:Optional[str]=Field(default=None)
    
class VerifyOTP(BaseModel):
	email: EmailStr
	otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class Login(BaseModel):
	email: EmailStr
	password: str = Field(min_length=8)


class PasswordResetRequest(BaseModel):
	email: EmailStr


class PasswordResetConfirm(BaseModel):
	email: EmailStr
	otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
	new_password: str = Field(min_length=8)