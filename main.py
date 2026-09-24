from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.institutions_router import institutions_router
from routers.students_router import students_router
from routers.superadmin_routers import superadmin_router
from routers.admin_router import admin_routers
from routers.files_router import files_router

app = FastAPI(title="CertiCertify API")

app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=False,
	allow_methods=["*"],
	allow_headers=["*"],
)
@app.get("/")
async def default():
    return {"message":"Welcome certicertify Backend Server"}
app.include_router(institutions_router)
app.include_router(students_router)
app.include_router(superadmin_router)
app.include_router(admin_routers)
app.include_router(files_router)