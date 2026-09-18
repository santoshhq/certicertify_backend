import logging
import re
import zipfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from openpyxl import load_workbook

from config.db_collections import institutions_collection, students_collections
from models.students_models import UpdateStudents
from schemas.students_schemas import get_all_documents, get_single_document
from services.aws_s3 import upload_student_certificate
from utils.jwt_token_auth import get_current_principal
from utils.generate_ids import generate_numeric_id

students_router = APIRouter(prefix="/students", tags=["Students"])
logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("roll_no_certificate_no", "student_name", "course_or_Acadamic", "month_year_pass")
ALLOWED_CERTIFICATE_EXTENSIONS = {"pdf", "jpg", "jpeg"}


class _CertificateFile:
	"""Duck-types the parts of UploadFile that services.aws_s3.upload_student_certificate reads."""

	def __init__(self, filename: str, content: bytes, content_type: str | None = None):
		self.filename = filename
		self.content_type = content_type
		self.file = BytesIO(content)


def _guess_certificate_content_type(filename: str) -> str:
	extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
	if extension == "pdf":
		return "application/pdf"
	if extension in ("jpg", "jpeg"):
		return "image/jpeg"
	return "application/octet-stream"


def _extract_zip_certificates(filename: str, content: bytes) -> list["_CertificateFile"]:
	try:
		archive = zipfile.ZipFile(BytesIO(content))
	except zipfile.BadZipFile as error:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail=f"Could not read '{filename}' as a zip archive",
		) from error

	extracted: list[_CertificateFile] = []
	with archive:
		for info in archive.infolist():
			if info.is_dir():
				continue
			name = Path(info.filename).name
			if not name or name.startswith(".") or "__MACOSX" in info.filename:
				continue
			extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
			if extension not in ALLOWED_CERTIFICATE_EXTENSIONS:
				continue
			extracted.append(
				_CertificateFile(name, archive.read(info), _guess_certificate_content_type(name))
			)
	return extracted


async def _expand_certificate_uploads(certificates: list[UploadFile]) -> list["_CertificateFile"]:
	expanded: list[_CertificateFile] = []
	for certificate in certificates:
		if not certificate.filename:
			continue
		content = await certificate.read()
		if certificate.filename.lower().endswith(".zip"):
			expanded.extend(_extract_zip_certificates(certificate.filename, content))
		else:
			expanded.append(_CertificateFile(certificate.filename, content, certificate.content_type))
	return expanded


def _internal_server_error(error: Exception) -> HTTPException:
	logger.exception("Student upload failed", exc_info=error)
	return HTTPException(
		status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
		detail="Unable to process student upload",
	)


def _normalize_header(value) -> str:
	if value is None:
		return ""
	return re.sub(r"\s+", " ", str(value)).strip().lower().rstrip("*").strip()


def _map_column(normalized: str) -> str | None:
	if not normalized:
		return None
	if normalized.startswith(("sl", "si no", "si.no", "serial", "s.no", "s no")):
		return None
	if "roll" in normalized:
		return "roll_no_certificate_no"
	if "sur" in normalized or "last name" in normalized:
		return "surname_lastName"
	if "course" in normalized or "academic" in normalized:
		return "course_or_Acadamic"
	if "month" in normalized or "year" in normalized:
		return "month_year_pass"
	if "grade" in normalized:
		return "grade"
	if "other" in normalized:
		return None
	if normalized.startswith("name"):
		return "student_name"
	return None


def _cell_text(value) -> str:
	if value is None:
		return ""
	return str(value).strip()


def _normalize_key(value: str | None) -> str:
	"""Canonical form for roll numbers and batch years: trimmed, single-spaced, uppercase.

	Applied on every write and every lookup so 'abc 101' and 'ABC101 ' resolve to the same student.
	"""
	if value is None:
		return ""
	return re.sub(r"\s+", " ", str(value)).strip().upper()


async def _require_own_institution_name(institution_name: str, principal: dict) -> None:
	institution = await institutions_collection.find_one({"institution_id": principal.get("institution_id")})
	if institution is None or institution.get("institution_name") != institution_name:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this institution")


@students_router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_students(
	excel_file: UploadFile = File(...),
	certificates: list[UploadFile] = File(default=[]),
	batch_year: str = Form(...),
	principal: dict = Depends(get_current_principal),
):
	try:
		batch_year = _normalize_key(batch_year)
		if not batch_year:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Batch year is required")
		if not excel_file.filename or not excel_file.filename.lower().endswith((".xlsx", ".xlsm")):
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .xlsx Excel files are supported")

		institution_id = principal.get("institution_id")
		institution = await institutions_collection.find_one({"institution_id": institution_id})
		if institution is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")
		institution_name = institution["institution_name"]

		contents = await excel_file.read()
		try:
			workbook = load_workbook(BytesIO(contents), data_only=True, read_only=True)
		except Exception as error:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not read the Excel file") from error

		sheet = workbook.active
		rows = sheet.iter_rows(values_only=True)
		try:
			header_row = next(rows)
		except StopIteration:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Excel file has no header row")

		data_rows = list(rows)
		column_fields = [_map_column(_normalize_header(header)) for header in header_row]
		if "roll_no_certificate_no" not in column_fields:
			raise HTTPException(
				status_code=status.HTTP_400_BAD_REQUEST,
				detail="Excel file is missing the Roll Number / Certificate Number column",
			)

		expanded_certificates = await _expand_certificate_uploads(certificates)

		certificates_by_roll_no = {
			_normalize_key(Path(certificate.filename).stem): certificate
			for certificate in expanded_certificates
		}
		matched_roll_numbers: set[str] = set()

		documents = []
		errors = []

		valid_rows = []
		# A student is unique by (roll number, batch year); the same roll number may repeat across batches.
		seen_in_file: set[tuple[str, str]] = set()

		for row_index, row in enumerate(data_rows, start=2):
			if row is None or all(cell is None or _cell_text(cell) == "" for cell in row):
				continue

			row_data: dict[str, str] = {}
			for field, cell in zip(column_fields, row):
				if field is None:
					continue
				row_data[field] = _cell_text(cell)

			missing = [field for field in REQUIRED_FIELDS if not row_data.get(field)]
			if missing:
				errors.append({"row": row_index, "reason": f"Missing required field(s): {', '.join(missing)}"})
				continue

			roll_no = row_data["roll_no_certificate_no"] = _normalize_key(row_data["roll_no_certificate_no"])
			student_key = (roll_no, batch_year)
			if student_key in seen_in_file:
				errors.append(
					{
						"row": row_index,
						"reason": f"Duplicate roll number '{roll_no}' for batch year '{batch_year}' in this file, not added",
					}
				)
				continue
			seen_in_file.add(student_key)

			valid_rows.append((row_index, roll_no, row_data))

		existing_students_keys: set[tuple[str, str]] = set()
		if valid_rows:
			existing_students = await students_collections.find(
				{"roll_no_certificate_no": {"$in": [roll_no for _, roll_no, _ in valid_rows]}},
				{"roll_no_certificate_no": 1, "batch_year": 1},
			).to_list(length=None)
			existing_students_keys = {
				(doc["roll_no_certificate_no"], doc.get("batch_year")) for doc in existing_students
			}

		for row_index, roll_no, row_data in valid_rows:
			if (roll_no, batch_year) in existing_students_keys:
				errors.append(
					{
						"row": row_index,
						"reason": f"Student with roll number '{roll_no}' and batch year '{batch_year}' already exists, not added",
					}
				)
				continue

			certificate_url = None
			certificate = certificates_by_roll_no.get(roll_no)
			if certificate is None:
				errors.append(
					{"row": row_index, "reason": f"Certificate not found for roll number '{roll_no}', not added"}
				)
				continue

			try:
				certificate_url = upload_student_certificate(certificate, institution_name, roll_no)
				matched_roll_numbers.add(roll_no)
			except HTTPException as error:
				errors.append({"row": row_index, "reason": f"Certificate upload failed: {error.detail}, not added"})
				continue

			document = {
				"student_id": str(uuid4()),
				"institution_id": institution_id,
				"institution_name": institution_name,
				"roll_no_certificate_no": roll_no,
				"student_name": row_data["student_name"],
				"surname_lastName": row_data.get("surname_lastName", ""),
				"course_or_Acadamic": row_data["course_or_Acadamic"],
				"month_year_pass": row_data["month_year_pass"],
				"grade": row_data.get("grade", ""),
				"batch_year": batch_year,
				"certificate_url": certificate_url,
                "certificate_id":generate_numeric_id(8)
			}
			documents.append(document)

		if documents:
			await students_collections.insert_many(documents)

		unmatched_certificates = [
			certificate.filename
			for stem, certificate in certificates_by_roll_no.items()
			if stem not in matched_roll_numbers
		]

		return {
			"inserted_count": len(documents),
			"students": get_all_documents(documents),
			"errors": errors,
			"unmatched_certificates": unmatched_certificates,
		}
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@students_router.get("/institution/{institution_name}")
async def get_students_by_institution(institution_name: str, principal: dict = Depends(get_current_principal)):
	try:
		await _require_own_institution_name(institution_name, principal)
		documents = await students_collections.find({"institution_name": institution_name}).to_list(length=None)
		return get_all_documents(documents)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@students_router.get("/institution/{institution_name}/year/{year}")
async def get_students_by_institution_and_year(
	institution_name: str,
	year: int,
	principal: dict = Depends(get_current_principal),
):
	try:
		await _require_own_institution_name(institution_name, principal)
		documents = await students_collections.find(
			{
				"institution_name": institution_name,
				"month_year_pass": {"$regex": str(year)},
			}
		).to_list(length=None)
		return get_all_documents(documents)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@students_router.get("/institution/{institution_name}/batch/{batch_year}")
async def get_students_by_institution_and_batch(
	institution_name: str,
	batch_year: str,
	principal: dict = Depends(get_current_principal),
):
	try:
		await _require_own_institution_name(institution_name, principal)
		documents = await students_collections.find(
			{"institution_name": institution_name, "batch_year": _normalize_key(batch_year)}
		).to_list(length=None)
		return get_all_documents(documents)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@students_router.get("/stats/{institution_id}")
async def get_student_stats(institution_id: str, principal: dict = Depends(get_current_principal)):
	try:
		if principal.get("institution_id") != institution_id:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this institution")

		pipeline = [
			{"$match": {"institution_id": institution_id}},
			{
				"$addFields": {
					"_department": {
						"$cond": [{"$in": ["$course_or_Acadamic", [None, ""]]}, "Unspecified", "$course_or_Acadamic"]
					},
					"_grade": {"$cond": [{"$in": ["$grade", [None, ""]]}, "Unspecified", "$grade"]},
					"_batch_year": {"$cond": [{"$in": ["$batch_year", [None, ""]]}, "Unspecified", "$batch_year"]},
					"_year_match": {"$regexFind": {"input": "$month_year_pass", "regex": r"\d{4}"}},
				}
			},
			{"$addFields": {"_year": {"$ifNull": ["$_year_match.match", "Unknown"]}}},
			{
				"$facet": {
					"by_year": [{"$group": {"_id": "$_year", "count": {"$sum": 1}}}, {"$sort": {"_id": 1}}],
					"by_department": [{"$group": {"_id": "$_department", "count": {"$sum": 1}}}, {"$sort": {"_id": 1}}],
					"by_grade": [{"$group": {"_id": "$_grade", "count": {"$sum": 1}}}, {"$sort": {"_id": 1}}],
					"by_batch_year": [{"$group": {"_id": "$_batch_year", "count": {"$sum": 1}}}, {"$sort": {"_id": 1}}],
					"total": [{"$count": "count"}],
				}
			},
		]

		result = await students_collections.aggregate(pipeline).to_list(length=1)
		facets = result[0] if result else {"by_year": [], "by_department": [], "by_grade": [], "by_batch_year": [], "total": []}

		return {
			"institution_id": institution_id,
			"total_students": facets["total"][0]["count"] if facets["total"] else 0,
			"by_year": {item["_id"]: item["count"] for item in facets["by_year"]},
			"by_department": {item["_id"]: item["count"] for item in facets["by_department"]},
			"by_grade": {item["_id"]: item["count"] for item in facets["by_grade"]},
			"by_batch_year": {item["_id"]: item["count"] for item in facets["by_batch_year"]},
		}
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@students_router.get("/{roll_no_certificate_no}")
async def get_student(roll_no_certificate_no: str):
	try:
		search_value = _normalize_key(roll_no_certificate_no)
		documents = await students_collections.find(
			{
				"$or": [
					{"roll_no_certificate_no": search_value},
					{"certificate_id": search_value},
				]
			}
		).to_list(length=None)
		if not documents:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
		return get_all_documents(documents)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error



@students_router.patch("/{roll_no_certificate_no}")
async def update_student(
	roll_no_certificate_no: str,
	student: UpdateStudents,
	principal: dict = Depends(get_current_principal),
):
	try:
		roll_no_certificate_no = _normalize_key(roll_no_certificate_no)
		existing = await students_collections.find_one({"roll_no_certificate_no": roll_no_certificate_no})
		if existing is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
		if existing.get("institution_id") != principal.get("institution_id"):
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this student")

		updates = student.model_dump(exclude_unset=True)
		if not updates:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one field is required")
		for key in ("roll_no_certificate_no", "batch_year"):
			if updates.get(key) is not None:
				updates[key] = _normalize_key(updates[key])

		# Keep (roll number, batch year) unique when either half of the key changes.
		if "roll_no_certificate_no" in updates or "batch_year" in updates:
			new_roll_no = updates.get("roll_no_certificate_no", existing.get("roll_no_certificate_no"))
			new_batch_year = updates.get("batch_year", existing.get("batch_year"))
			clash = await students_collections.find_one(
				{
					"roll_no_certificate_no": new_roll_no,
					"batch_year": new_batch_year,
					"student_id": {"$ne": existing.get("student_id")},
				}
			)
			if clash is not None:
				raise HTTPException(
					status_code=status.HTTP_409_CONFLICT,
					detail=f"Student with roll number '{new_roll_no}' and batch year '{new_batch_year}' already exists",
				)

		result = await students_collections.update_one(
			{"roll_no_certificate_no": roll_no_certificate_no},
			{"$set": updates},
		)
		if result.matched_count == 0:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

		updated_roll_no = updates.get("roll_no_certificate_no", roll_no_certificate_no)
		document = await students_collections.find_one({"roll_no_certificate_no": updated_roll_no})
		return get_single_document(document)
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error


@students_router.delete("/{roll_no_certificate_no}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(roll_no_certificate_no: str, principal: dict = Depends(get_current_principal)):
	try:
		roll_no_certificate_no = _normalize_key(roll_no_certificate_no)
		existing = await students_collections.find_one({"roll_no_certificate_no": roll_no_certificate_no})
		if existing is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
		if existing.get("institution_id") != principal.get("institution_id"):
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this student")

		result = await students_collections.delete_one({"roll_no_certificate_no": roll_no_certificate_no})
		if result.deleted_count == 0:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
	except HTTPException:
		raise
	except Exception as error:
		raise _internal_server_error(error) from error
