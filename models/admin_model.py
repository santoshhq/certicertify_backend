from pydantic import BaseModel, Field , EmailStr
from typing import Optional
class Admin(BaseModel):
    admin_name:str=Field(...,)
    email:EmailStr=Field(...,)
    mobilenumber:str=Field(...,)
    admin_userId:str=Field(...,min_length=8, max_length=8)
    password:str=Field(...,min_length=8)
    

class UpdateAdmin(BaseModel):
    admin_name:Optional[str]=Field(default=None)
    email:Optional[EmailStr]=Field(default=None)
    mobilenumber:Optional[str]=Field(default=None)
    admin_userId:Optional[str]=Field(default=None)
    password:Optional[str]=Field(default=None)

    
    
class Login(BaseModel):
    admin_loginId:str=Field(...,)
    password:str=Field(...,)