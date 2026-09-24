import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from utils.generate_ids import generate_id
from config.db_collections import institutions_collection
from models.institutions_model import (
	Login,
	PasswordResetConfirm,
	PasswordResetRequest,
	Register,
	UpdateBase,
	VerifyOTP,
    InstitutionStatus
)
from schemas.institutions_schemas import get_all_documents, get_single_document
from schemas.students_schemas import get_single_document as get_single_student_document
from services.email_service import institution_account_verify, institution_password_reset
from services.certificate_replace import find_student_for_replace, replace_student_certificate
from utils.jwt_token_auth import create_access_token, get_current_institution,get_current_superadmin


institutions_router = APIRouter(prefix="/institutions", tags=["Institutions"])
logger = logging.getLogger(__name__)


def _internal_server_error(error: Exception) -> HTTPException:
	logger.exception("Institution operation failed", exc_info=error)
	return HTTPException(
		status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
		detail="Unable to process institution request",
	)


def _as_aware_utc(value: datetime | None) -> datetime | None:
	if value is None:
		return None
	if value.tzinfo is None:
		return value.replace(tzinfo=timezone.utc)
	return value


def _require_self(institution_id: str, principal: dict) -> None:
	if principal.get("institution_id") != institution_id:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this institution")


@institutions_router.post("/register", status_code=status.HTTP_201_CREATED)
async def create_institution(institution: Register):
	document = None
	try:
		document = institution.model_dump()
		document["institution_id"] = str(uuid4())
		document["otp_code"] = f"{secrets.randbelow(1_000_000):06d}"
		document["otp_expires_at"] = datetime.now(timezone.utc) + timedelta(minutes=5)
		document["otp_verified"] = False
		document["role"] = "institution"
		document["unique_id"] = generate_id(8)
		await institutions_collection.insert_one(document)
		await institution_account_verify(document["email_id"], document["otp_code"])
		return get_single_document(document)
	except Exception as error:
		if document is not None:
			await institutions_collection.delete_one({"institution_id": document["institution_id"]})
		raise _internal_server_error(error) from error


@institutions_router.post("/login")
async def login_institution(credentials: Login):
    try:
        document = await institutions_collection.find_one(
            {"email_id": str(credentials.email_id)}
        )
        if document is None or credentials.password != document.get("password"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        if not document.get("otp_verified", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email OTP verification required",
            )
        if not document.get("status", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your Account is Inactive. Please Contact Admin or Superadmin",
            )
        token = create_access_token(
            user_id=document["institution_id"],
            role="institution",
            institution_id=document["institution_id"],
            email=document["email_id"],
        )
        return {
            "access_token": token,
            "token_type": "bearer",
        }
    except HTTPException:
        raise
    except Exception as error:
        raise _internal_server_error(error) from error

@institutions_router.get("/superadmin_status")
async def get_active_institution(
    principal: dict = Depends(get_current_institution)
):
    institution = await institutions_collection.find_one(
        {"institution_id": principal["institution_id"]}
    )

    if not institution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Institution not found"
        )

    if institution.get("superadmin_status") != InstitutionStatus.APPROVED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Institution is not approved"
        )

    return get_single_document(institution)

@institutions_router.post("/password-reset/request")
async def request_password_reset(payload: PasswordResetRequest):
	try:
		document = await institutions_collection.find_one({"email_id": str(payload.email_id)})
		if document is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")
		if not document.get("otp_verified", False):
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email OTP verification required")

		otp = f"{secrets.randbelow(1_000_000):06d}"
		expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
		await institutions_collection.update_one(
			{"institution_id": document["institution_id"]},
			{"$set": {"password_reset_otp": otp, "password_reset_expires_at": expires_at}},
		)
		await institution_password_reset(str(payload.email_id), otp)
		return {"message": "Password reset OTP sent"}
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@institutions_router.post("/password-reset/confirm")
async def confirm_password_reset(payload: PasswordResetConfirm):
	try:
		document = await institutions_collection.find_one({"email_id": str(payload.email_id)})
		if document is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")
		if document.get("password_reset_otp") != payload.otp:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid password reset OTP")
		if _as_aware_utc(document.get("password_reset_expires_at")) is None or _as_aware_utc(document["password_reset_expires_at"]) < datetime.now(timezone.utc):
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password reset OTP has expired")

		await institutions_collection.update_one(
			{"institution_id": document["institution_id"]},
			{"$set": {"password": payload.new_password}, "$unset": {"password_reset_otp": "", "password_reset_expires_at": ""}},
		)
		return {"message": "Password reset successfully"}
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@institutions_router.post("/verify-otp")
async def verify_otp(payload: VerifyOTP):
	try:
		document = await institutions_collection.find_one({"email_id": str(payload.email_id)})
		if document is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")
		if document.get("otp_verified", False):
			return get_single_document(document)
		if document.get("otp_code") != payload.otp:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP")
		expires_at = _as_aware_utc(document.get("otp_expires_at"))
		if expires_at is None or expires_at < datetime.now(timezone.utc):
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP has expired")

		await institutions_collection.update_one(
			{"email_id": payload.email_id},
			{"$set": {"otp_verified": True}, "$unset": {"otp_code": "", "otp_expires_at": ""}},
		)
		document["otp_verified"] = True
		return get_single_document(document)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error





@institutions_router.get("/institution/{institution_id}")
async def get_institution(institution_id: str, principal: dict = Depends(get_current_institution)):
	try:
		document = await institutions_collection.find_one({"institution_id": institution_id})
		if document is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")
		return get_single_document(document)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@institutions_router.patch("/update-institution/{institution_id}")
async def update_institution(
	institution_id: str,
	institution: UpdateBase,
	principal: dict = Depends(get_current_institution),
):
	try:
		_require_self(institution_id, principal)
		updates = institution.model_dump(exclude_unset=True)
		if not updates:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one field is required")

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


@institutions_router.delete("/delete-institution/{institution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_institution(institution_id: str, principal: dict = Depends(get_current_institution)):
	try:
		_require_self(institution_id, principal)
		result = await institutions_collection.delete_one({"institution_id": institution_id})
		if result.deleted_count == 0:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@institutions_router.patch("/students/id/{student_id}/certificate", status_code=status.HTTP_200_OK)
async def institution_replace_certificate_by_student_id(
	student_id: str,
	certificate: UploadFile = File(...),
	principal: dict = Depends(get_current_institution),
):
	"""Replace one specific student's certificate (old file is deleted from storage)."""
	try:
		existing = await find_student_for_replace(
			{"student_id": student_id, "institution_id": principal.get("institution_id")}
		)
		document = await replace_student_certificate(existing, certificate)
		return get_single_student_document(document)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@institutions_router.patch("/students/{roll_no}/certificate", status_code=status.HTTP_200_OK)
async def institution_replace_student_certificate(
	roll_no: str,
	certificate: UploadFile = File(...),
	batch_year: str | None = None,
	principal: dict = Depends(get_current_institution),
):
	"""Replace by roll number; pass batch_year when the roll number exists in several batches."""
	try:
		query = {
			"roll_no": " ".join(str(roll_no).strip().upper().split()),
			"institution_id": principal.get("institution_id"),
		}
		if batch_year:
			query["batch_year"] = " ".join(str(batch_year).strip().upper().split())
		existing = await find_student_for_replace(query)
		document = await replace_student_certificate(existing, certificate)
		return get_single_student_document(document)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error

       

