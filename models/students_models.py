from pydantic import BaseModel,Field
from typing import Optional
class Students(BaseModel):
    roll_no_certificate_no:str=Field(...,)
    student_name:str=Field(...,)
    surname_lastName:str=Field(...,)
    course_or_Acadamic:str=Field(...,)
    month_year_pass:str=Field(...,)
    grade:str
    batch_year:str=Field(...,)
    certificate_url:str
    
    
class UpdateStudents(BaseModel):
    roll_no_certificate_no:Optional[str]=Field(default=None)
    student_name:Optional[str]=Field(default=None)
    surname_lastName:Optional[str]=Field(default=None)
    course_or_Acadamic:Optional[str]=Field(default=None)
    month_year_pass:Optional[str]=Field(default=None)
    grade:Optional[str]=None
    batch_year:Optional[str]=None
    certificate_url:Optional[str]=None
    
    