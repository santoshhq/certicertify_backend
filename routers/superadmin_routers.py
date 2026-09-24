from models.superadmin_models import (
	Login,
	PasswordResetConfirm,
	PasswordResetRequest,
	SuperAdmin,
	UpdateSuperAdmin,
	VerifyOTP,
)
from config.db_collections import institutions_collection, superadmin_collection, students_collections
from utils.generate_ids import generate_id
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from pathlib import Path
import logging
import os
import secrets
from zoneinfo import ZoneInfo
from schemas.superadmin_schemas import single_document,profile_info
from schemas.institutions_schemas import get_all_documents, get_single_document
from schemas.admin_schemas import get_all_admin_doc, single_admin_doc
from services.email_service import admin_account_created, institution_email_changed, superadmin_account_verify, superadmin_password_reset
from services.ftps_storage import delete_certificate_by_url, upload_student_certificate
from utils.jwt_token_auth import create_access_token, get_current_superadmin
from models.institutions_model import InstitutionStatus, UpdateBase
from config.db_collections import admins_collection
from models.admin_model import Admin, UpdateAdmin
from models.students_models import UpdateStudents
from schemas.students_schemas import get_all_documents as get_all_student_documents, get_single_document as get_single_student_document
from routers.students_router import upload_students, create_single_student
from models.institutions_model import Register
superadmin_router=APIRouter(prefix="/superadmin",tags=["Super Admin"])
logger = logging.getLogger("uvicorn.error")


def _internal_server_error(error: Exception) -> HTTPException:
	return HTTPException(
		status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
		detail="Unable to process superadmin request",
	)


def _as_aware_utc(value: datetime | None) -> datetime | None:
	if value is None:
		return None
	if value.tzinfo is None:
		return value.replace(tzinfo=timezone.utc)
	return value

@superadmin_router.get("/profile-info")
async def superadmin_profileInfo(current_superadmin:dict=Depends(get_current_superadmin)):
    try:
        account_info=await superadmin_collection.find_one({"superadmin_id":current_superadmin.get("sub")})
        return profile_info(account_info)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@superadmin_router.patch("/profile-info")
async def superadmin_update_profile(
    requests: UpdateSuperAdmin,
    current_superadmin: dict = Depends(get_current_superadmin),
):
    try:
        updates = requests.model_dump(exclude_unset=True)
        # Password changes go through the OTP reset flow; email is the login identity.
        updates.pop("password", None)
        updates.pop("email", None)
        updates = {k: v for k, v in updates.items() if v is not None and str(v).strip()}
        if not updates:
            raise HTTPException(status_code=400, detail="At least one of fullname or mobilenumber is required")
        result = await superadmin_collection.update_one(
            {"superadmin_id": current_superadmin.get("sub")},
            {"$set": updates},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Superadmin not found")
        account_info = await superadmin_collection.find_one({"superadmin_id": current_superadmin.get("sub")})
        return profile_info(account_info)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Unable to update profile") from e






@superadmin_router.post("/register")
async def register(requests:SuperAdmin):
    try:
        document=requests.model_dump()
        superadmin_unique_id=generate_id(7)
        payload={
            "superadmin_id":str(uuid4()),
            "unique_id":superadmin_unique_id,
            "fullname":document.get("fullname"),
            "email":document.get("email"),
            "mobilenumber":document.get("mobilenumber"),
            "password":document.get("password"),
            "otp_code": f"{secrets.randbelow(1_000_000):06d}",
            "otp_expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            "otp_verified":False,
            "role":"superadmin"

        }
        await superadmin_collection.insert_one(payload)
        await superadmin_account_verify(payload["email"], payload["otp_code"])
        return {"message": "Superadmin registered. Verification OTP sent."}
    except Exception as error:
        raise HTTPException(status_code=500, detail="Unable to register superadmin") from error
    
    
@superadmin_router.post("/login")
async def login_institution(credentials: Login):
	try:
		document = await superadmin_collection.find_one({"email": str(credentials.email)})
		if document is None or credentials.password != document.get("password"):
			raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
		if not document.get("otp_verified", False):
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email OTP verification required")

		token = create_access_token(
			user_id=document["superadmin_id"],
			role="superadmin",
			organization_id=document["superadmin_id"],
			email=document["email"],
		)
		return {
			"access_token": token,
			"token_type": "bearer",
		} 
	except HTTPException:
		raise
	except Exception as error:
		raise HTTPException(status_code=500, detail=str(error))
    
    
@superadmin_router.post("/verify-otp")
async def verify_otp(payload: VerifyOTP):
	try:
		document = await superadmin_collection.find_one({"email": str(payload.email)})
		if document is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Superadmin not found")
		if document.get("otp_verified", False):
			return single_document(document)
		if document.get("otp_code") != payload.otp:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP")
		expires_at = _as_aware_utc(document.get("otp_expires_at"))
		if expires_at is None or expires_at < datetime.now(timezone.utc):
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP has expired")

		await superadmin_collection.update_one(
			{"email": str(payload.email)},
			{"$set": {"otp_verified": True}, "$unset": {"otp_code": "", "otp_expires_at": ""}},
		)
		document["otp_verified"] = True
		return single_document(document)
	except HTTPException:
		raise
	except Exception as error:
		raise HTTPException(status_code=500, detail=str(error))



@superadmin_router.post("/password-reset/request")
async def request_password_reset(payload: PasswordResetRequest):
	try:
		document = await superadmin_collection.find_one({"email": str(payload.email)})
		if document is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Superadmin not found")
		if not document.get("otp_verified", False):
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email OTP verification required")

		otp = f"{secrets.randbelow(1_000_000):06d}"
		expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
		await superadmin_collection.update_one(
			{"superadmin_id": document["superadmin_id"]},
			{"$set": {"password_reset_otp": otp, "password_reset_expires_at": expires_at}},
		)
		await superadmin_password_reset(str(payload.email), otp)
		return {"message": "Password reset OTP sent"}
	except HTTPException:
		raise
	except Exception as error:
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail="Unable to process password reset request",
		) from error


@superadmin_router.post("/password-reset/confirm")
async def confirm_password_reset(payload: PasswordResetConfirm):
	try:
		document = await superadmin_collection.find_one({"email": str(payload.email)})
		if document is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Superadmin not found")
		if document.get("password_reset_otp") != payload.otp:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid password reset OTP")

		expires_at = _as_aware_utc(document.get("password_reset_expires_at"))
		if expires_at is None or expires_at < datetime.now(timezone.utc):
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password reset OTP has expired")

		await superadmin_collection.update_one(
			{"superadmin_id": document["superadmin_id"]},
			{
				"$set": {"password": payload.new_password},
				"$unset": {"password_reset_otp": "", "password_reset_expires_at": ""},
			},
		)
		return {"message": "Password reset successfully"}
	except HTTPException:
		raise
	except Exception as error:
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail="Unable to confirm password reset",
		) from error
  
#---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
#SuperAdmin
@superadmin_router.get("/superadmin-get-all-institutes")
async def get_all_institutions(principal: dict = Depends(get_current_superadmin)):
	try:
		documents = await institutions_collection.find().to_list(length=None)
		return get_all_documents(documents)
	except Exception as error:
		raise _internal_server_error(error) from error


@superadmin_router.patch("/superadmin-update-institution/{institution_id}")
async def update_institution(
	institution_id: str,
	institution: UpdateBase,
	principal: dict = Depends(get_current_superadmin),
):
	try:
		updates = institution.model_dump(exclude_unset=True)
		if not updates:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one field is required")

		existing = await institutions_collection.find_one({"institution_id": institution_id})
		if not existing:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")

		# Capture the previous email before the write so the old address can be alerted.
		old_email = str(existing.get("email_id") or "").strip()
		new_email = str(updates.get("email_id") or "").strip()
		email_changed = bool(new_email) and bool(old_email) and new_email.lower() != old_email.lower()

		if email_changed:
			# Alert the previous address BEFORE the account switches over, so a mail
			# failure leaves the institution on its original, still-reachable email.
			try:
				await institution_email_changed(
					recipient=old_email,
					institution_name=(
						existing.get("institution_name")
						or existing.get("name")
						or "your institution"
					),
					old_email=old_email,
					new_email=new_email,
					superadmin_email=principal.get("email"),
					changed_at=datetime.now(
						ZoneInfo("Asia/Kolkata")
					).strftime("%d %b %Y, %I:%M %p IST"),
				)	
				logger.info("Institution %s: change alert accepted by SMTP for old address %s (%s -> %s)", institution_id, old_email, old_email, new_email)
			except Exception as mail_error:
				logger.error("Institution %s email change alert to %s failed: %s", institution_id, old_email, mail_error)
				raise HTTPException(
					status_code=status.HTTP_502_BAD_GATEWAY,
					detail=f"Couldn't notify the current email address ({old_email}), so the email was not changed. Please try again.",
				) from mail_error

		result = await institutions_collection.update_one(
			{"institution_id": institution_id},
			{"$set": updates},
		)
		if result.matched_count == 0:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")

		document = await institutions_collection.find_one({"institution_id": institution_id})
		return get_single_document(document)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@superadmin_router.delete("/delete-institution/{institution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_institution(institution_id: str, principal: dict = Depends(get_current_superadmin)):
	try:
		result = await institutions_collection.delete_one({"institution_id": institution_id})
		if result.deleted_count == 0:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error

#---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
#Admin

@superadmin_router.post("/admin-creation")
async def add_new_admin(requests:Admin, current_superadmin:dict=Depends(get_current_superadmin)):
	try:
		document = requests.model_dump(mode="json")
		payload = {
			"admin_id": str(uuid4()),
			"admin_loginId": document.get("admin_userId"),
			"admin_name": document.get("admin_name"),
			"email": document.get("email"),
			"mobilenumber": document.get("mobilenumber"),
			"password": document.get("password"),
			"access_level": document.get("access_level"),
			"permissions": document.get("permissions"),
			"status": document.get("status", True),
			"superadmin_id": current_superadmin["sub"],
			"role": "admin",
		}
		id_acc = await admins_collection.find_one({"admin_loginId": payload["admin_loginId"]})
		if id_acc:
			raise HTTPException(status_code=400, detail="Admin login ID already exists")
		check_acc = await admins_collection.find_one(
			{"email": payload["email"], "superadmin_id": payload["superadmin_id"]}
		)
		if check_acc:
			raise HTTPException(status_code=400, detail="The email is already registered")
		await admins_collection.insert_one(payload)
		await admin_account_created(
			str(payload["email"]),
			payload["admin_name"],
			payload["admin_loginId"],
			payload["password"],
		)
		return {"message": "Admin registration successful"}
	except HTTPException:
		raise
	except Exception as error:
		raise HTTPException(status_code=500, detail="Unable to create admin account") from error


@superadmin_router.get("/admins")
async def get_all_admins(current_superadmin: dict = Depends(get_current_superadmin)):
	try:
		documents = await admins_collection.find(
			{"superadmin_id": current_superadmin["sub"]}
		).to_list(length=None)
		return get_all_admin_doc(documents)
	except Exception as error:
		raise _internal_server_error(error) from error


@superadmin_router.patch("/admin/{admin_id}")
async def update_admin(
	admin_id: str,
	admin: UpdateAdmin,
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		updates = admin.model_dump(exclude_unset=True, mode="json")
		if not updates:
			raise HTTPException(
				status_code=status.HTTP_400_BAD_REQUEST,
				detail="At least one field is required",
			)

		if "admin_userId" in updates:
			updates["admin_loginId"] = updates.pop("admin_userId")

		if "email" in updates:
			updates["email"] = str(updates["email"])

		if "admin_loginId" in updates:
			login_id_exists = await admins_collection.find_one(
				{
					"admin_loginId": updates["admin_loginId"],
					"admin_id": {"$ne": admin_id},
				}
			)
			if login_id_exists:
				raise HTTPException(status_code=400, detail="Admin login ID already exists")

		if "email" in updates:
			email_exists = await admins_collection.find_one(
				{
					"email": updates["email"],
					"superadmin_id": current_superadmin["sub"],
					"admin_id": {"$ne": admin_id},
				}
			)
			if email_exists:
				raise HTTPException(status_code=400, detail="The email is already registered")

		result = await admins_collection.update_one(
			{"admin_id": admin_id, "superadmin_id": current_superadmin["sub"]},
			{"$set": updates},
		)
		if result.matched_count == 0:
			raise HTTPException(status_code=404, detail="Admin not found")

		document = await admins_collection.find_one({"admin_id": admin_id})
		return single_admin_doc(document)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@superadmin_router.delete("/admin/{admin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin(
	admin_id: str,
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		result = await admins_collection.delete_one(
			{"admin_id": admin_id, "superadmin_id": current_superadmin["sub"]}
		)
		if result.deleted_count == 0:
			raise HTTPException(status_code=404, detail="Admin not found")
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@superadmin_router.post("/add-instution")
async def add_instution(
	requests: Register,
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		document = requests.model_dump()
		check_existing_acc = await institutions_collection.find_one({"institution_name": document.get("institution_name")})
		if check_existing_acc:
			raise HTTPException(status_code=400, detail="Institution name already present")

		institution_id = str(uuid4())
		payload = {
			"name": document.get("name"),
			"email_id": document.get("email_id"),
			"institution_name": document.get("institution_name"),
			"institutional_code": document.get("institutional_code"),
			"gst_number": document.get("gst_number"),
			"postal_code": document.get("postal_code"),
			"city": document.get("city"),
			"state": document.get("state"),
			"country": document.get("country"),
			"mobile_no": document.get("mobile_no"),
			"password": document.get("password"),
			"institution_id": institution_id,
			"otp_verified": True,
			"role": "institution",
			"unique_id": generate_id(8),
			"superadmin_status": InstitutionStatus.APPROVED,
			"status": True,
		}
		await institutions_collection.insert_one(payload)
		return get_single_document(payload)
	except HTTPException:
		raise
	except Exception as error:
		raise HTTPException(status_code=500, detail="Unable to create institution") from error
#------------------------------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------------------------------
#Students 

@superadmin_router.post("/students/upload", status_code=status.HTTP_201_CREATED)
async def superadmin_upload_students(
	excel_file: UploadFile = File(...),
	certificates: list[UploadFile] = File(default=[]),
	batch_year: str = Form(...),
	institution_id: str = Form(...),
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		return await upload_students(
			excel_file=excel_file,
			certificates=certificates,
			batch_year=batch_year,
			principal={"role": "superadmin", "institution_id": institution_id},
		)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error

@superadmin_router.post("/students", status_code=status.HTTP_201_CREATED)
async def superadmin_add_student(
	institution_id: str = Form(...),
	batch_year: str = Form(...),
	certificate_no: str = Form(...),
	roll_no: str = Form(...),
	student_name: str = Form(...),
	surname_lastName: str = Form(default=""),
	course_or_Acadamic: str = Form(...),
	month_year_pass: str = Form(...),
	grade: str = Form(default=""),
	certificate: UploadFile = File(...),
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		return await create_single_student(
			principal={"role": "superadmin", "institution_id": institution_id},
			batch_year=batch_year,
			certificate_no=certificate_no,
			roll_no=roll_no,
			student_name=student_name,
			surname_lastName=surname_lastName,
			course_or_Acadamic=course_or_Acadamic,
			month_year_pass=month_year_pass,
			grade=grade,
			certificate=certificate,
		)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


def _student_key(value: str) -> str:
	return " ".join(str(value).strip().upper().split())


def _certificate_max_size_bytes() -> int:
	try:
		max_size_mb = int(os.getenv("CERTIFICATE_MAX_SIZE_MB", "10"))
	except ValueError:
		max_size_mb = 10
	return max(max_size_mb, 1) * 1024 * 1024


async def _read_replacement_certificate(certificate: UploadFile) -> None:
	filename = certificate.filename or ""
	if not filename:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Certificate file is required")
	if Path(filename).name != filename:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid certificate filename")

	extension = Path(filename).suffix.lower()
	if extension not in {".pdf", ".jpg", ".jpeg"}:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF, JPG and JPEG certificates are allowed")

	max_size_bytes = _certificate_max_size_bytes()
	content = await certificate.read(max_size_bytes + 1)
	if not content:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Certificate file cannot be empty")
	if len(content) > max_size_bytes:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Certificate file exceeds the maximum allowed size")
	certificate.file.seek(0)


@superadmin_router.get("/students/institution/{institution_name}")
async def superadmin_get_students_by_institution(
	institution_name: str,
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		documents = await students_collections.find({"institution_name": institution_name}).to_list(length=None)
		return get_all_student_documents(documents)
	except Exception as error:
		raise _internal_server_error(error) from error


@superadmin_router.get("/students/institution/{institution_name}/year/{year}")
async def superadmin_get_students_by_year(
	institution_name: str,
	year: int,
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		documents = await students_collections.find(
			{"institution_name": institution_name, "month_year_pass": {"$regex": str(year)}}
		).to_list(length=None)
		return get_all_student_documents(documents)
	except Exception as error:
		raise _internal_server_error(error) from error


@superadmin_router.get("/students/institution/{institution_name}/batch/{batch_year}")
async def superadmin_get_students_by_batch(
	institution_name: str,
	batch_year: str,
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		documents = await students_collections.find(
			{"institution_name": institution_name, "batch_year": _student_key(batch_year)}
		).to_list(length=None)
		return get_all_student_documents(documents)
	except Exception as error:
		raise _internal_server_error(error) from error


@superadmin_router.get("/students/stats/{institution_id}")
async def superadmin_get_student_stats(
	institution_id: str,
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		result = await students_collections.aggregate(
			[
				{"$match": {"institution_id": institution_id}},
				{
					"$facet": {
						"total": [{"$count": "count"}],
						"by_year": [
							{"$group": {"_id": "$month_year_pass", "count": {"$sum": 1}}},
							{"$sort": {"_id": 1}},
						],
						"by_department": [
							{"$group": {"_id": "$course_or_Acadamic", "count": {"$sum": 1}}},
							{"$sort": {"_id": 1}},
						],
						"by_grade": [
							{"$group": {"_id": "$grade", "count": {"$sum": 1}}},
							{"$sort": {"_id": 1}},
						],
						"by_batch_year": [
							{"$group": {"_id": "$batch_year", "count": {"$sum": 1}}},
							{"$sort": {"_id": 1}},
						],
					}
				},
			]
		).to_list(length=1)
		facets = result[0] if result else {}
		return {
			"institution_id": institution_id,
			"total_students": facets.get("total", [{}])[0].get("count", 0) if facets.get("total") else 0,
			"by_year": {item["_id"]: item["count"] for item in facets.get("by_year", [])},
			"by_department": {item["_id"]: item["count"] for item in facets.get("by_department", [])},
			"by_grade": {item["_id"]: item["count"] for item in facets.get("by_grade", [])},
			"by_batch_year": {item["_id"]: item["count"] for item in facets.get("by_batch_year", [])},
		}
	except Exception as error:
		raise _internal_server_error(error) from error


@superadmin_router.get("/students/{roll_no}")
async def superadmin_get_student(
	roll_no: str,
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		document = await students_collections.find_one(
			{"roll_no": _student_key(roll_no)}
		)
		if document is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
		return get_single_student_document(document)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@superadmin_router.patch("/students/{roll_no}/certificate", status_code=status.HTTP_200_OK)
async def superadmin_replace_student_certificate(
	roll_no: str,
	certificate: UploadFile = File(...),
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		student_key = _student_key(roll_no)
		existing = await students_collections.find_one({"roll_no": student_key})
		if existing is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

		await _read_replacement_certificate(certificate)
		old_certificate_url = existing.get("certificate_url")
		certificate_url = upload_student_certificate(
			certificate,
			existing.get("institution_name", ""),
			existing.get("batch_year", ""),
			existing.get("course_or_Acadamic", ""),
			student_key,
			replacing_url=old_certificate_url,
		)
		result = await students_collections.update_one(
			{"student_id": existing["student_id"]},
			{"$set": {"certificate_url": certificate_url}},
		)
		if result.matched_count == 0:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
		if old_certificate_url != certificate_url:
			delete_certificate_by_url(old_certificate_url)

		updated_student = await students_collections.find_one({"student_id": existing["student_id"]})
		return get_single_student_document(updated_student)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@superadmin_router.patch("/students/{roll_no}")
async def superadmin_update_student(
	roll_no: str,
	student: UpdateStudents,
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		roll_no = _student_key(roll_no)
		existing = await students_collections.find_one({"roll_no": roll_no})
		if existing is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
		updates = student.model_dump(exclude_unset=True)
		if not updates:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one field is required")
		for key in ("roll_no", "batch_year"):
			if updates.get(key) is not None:
				updates[key] = _student_key(updates[key])
		if "roll_no" in updates or "batch_year" in updates:
			new_roll_no = updates.get("roll_no", existing.get("roll_no"))
			new_batch_year = updates.get("batch_year", existing.get("batch_year"))
			clash = await students_collections.find_one(
				{
					"institution_id": existing.get("institution_id"),
					"roll_no": new_roll_no,
					"batch_year": new_batch_year,
					"student_id": {"$ne": existing.get("student_id")},
				}
			)
			if clash is not None:
				raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Student already exists")
		result = await students_collections.update_one(
			{"student_id": existing["student_id"]}, {"$set": updates}
		)
		if result.matched_count == 0:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
		document = await students_collections.find_one({"student_id": existing["student_id"]})
		return get_single_student_document(document)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@superadmin_router.delete("/students/{roll_no}", status_code=status.HTTP_204_NO_CONTENT)
async def superadmin_delete_student(
	roll_no: str,
	current_superadmin: dict = Depends(get_current_superadmin),
):
	try:
		result = await students_collections.delete_one(
			{"roll_no": _student_key(roll_no)}
		)
		if result.deleted_count == 0:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


#-------------------------------------------------------------------------------------------
