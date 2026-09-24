import os
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from config.db_collections import students_collections
from services.ftps_storage import delete_certificate_by_url, upload_student_certificate


# ============================================================
# Shared "replace a student's certificate" logic used by the
# superadmin, admin and institution routers.
# ============================================================


def _certificate_max_size_bytes() -> int:
	try:
		max_size_mb = int(os.getenv("CERTIFICATE_MAX_SIZE_MB", "10"))
	except ValueError:
		max_size_mb = 10
	return max(max_size_mb, 1) * 1024 * 1024


async def read_replacement_certificate(certificate: UploadFile) -> None:
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


async def find_student_for_replace(query: dict) -> dict:
	"""
	Find exactly one student. Roll numbers are only unique per
	institution + batch year, so refuse to guess when several match.
	"""
	matches = await students_collections.find(query).to_list(length=2)
	if not matches:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
	if len(matches) > 1:
		raise HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail=(
				"More than one student matches this roll number. Pass batch_year "
				"(and institution_id) or use the /students/id/{student_id}/certificate endpoint"
			),
		)
	return matches[0]


async def replace_student_certificate(student: dict, certificate: UploadFile) -> dict:
	"""
	Upload the new certificate to FTPS (compressed if > 200 KB), point the
	student's certificate_url at it, then delete the old file.
	Returns the updated student document.
	"""
	await read_replacement_certificate(certificate)

	old_certificate_url = student.get("certificate_url")
	certificate_url = await run_in_threadpool(
		upload_student_certificate,
		certificate,
		student.get("institution_name", ""),
		student.get("batch_year", ""),
		student.get("course_or_Acadamic", ""),
		student.get("roll_no", ""),
		old_certificate_url,
	)

	result = await students_collections.update_one(
		{"student_id": student["student_id"]},
		{"$set": {"certificate_url": certificate_url}},
	)
	if result.matched_count == 0:
		# Student was deleted meanwhile: don't leave an orphan file behind.
		if certificate_url != old_certificate_url:
			await run_in_threadpool(delete_certificate_by_url, certificate_url)
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

	if old_certificate_url != certificate_url:
		await run_in_threadpool(delete_certificate_by_url, old_certificate_url)

	return await students_collections.find_one({"student_id": student["student_id"]})
