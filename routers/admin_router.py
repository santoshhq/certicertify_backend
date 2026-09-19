from config.db_collections import admins_collection, institutions_collection, students_collections
from models.admin_model import Login
from models.institutions_model import UpdateBase
from models.students_models import UpdateStudents
from schemas.institutions_schemas import get_all_documents, get_single_document
from schemas.students_schemas import get_all_documents as get_all_student_documents, get_single_document as get_single_student_document
from fastapi import APIRouter, File, Form, HTTPException, Depends, UploadFile, status
from utils.jwt_token_auth import get_current_admin, create_access_token
from routers.students_router import upload_students
from services.aws_s3 import upload_student_certificate
from routers.superadmin_routers import _read_replacement_certificate


admin_routers=APIRouter(prefix="/admin",tags=["Admin"])


def _internal_server_error(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unable to process admin request",
    )


@admin_routers.post("/login")
async def admin_login(requests:Login):
    try:
        document= requests.model_dump()
        check_acc= await admins_collection.find_one({"admin_loginId":document.get("admin_loginId")})
        if not check_acc :
            raise HTTPException(status_code=404, detail="Admin Account Not Found !")
        if check_acc.get("password")!= document.get("password"):
            raise HTTPException(status_code=400, detail="Invalid admin_userId and passowrd")
        token=create_access_token(
            user_id=check_acc.get("admin_id"),
            role=check_acc.get("role"),
            email=check_acc.get("email")
        )
        return {
            "access_token": token,
            "token_type": "bearer",
        }
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))

#---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
#Institutions (same as superadmin)

@admin_routers.get("/admin-get-all-institutes")
async def get_all_institutions(current_admin: dict = Depends(get_current_admin)):
    try:
        documents = await institutions_collection.find().to_list(length=None)
        return get_all_documents(documents)
    except Exception as error:
        raise _internal_server_error(error) from error


@admin_routers.patch("/admin-update-institution/{institution_id}")
async def update_institution(
    institution_id: str,
    institution: UpdateBase,
    current_admin: dict = Depends(get_current_admin),
):
    try:
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


@admin_routers.delete("/delete-institution/{institution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_institution(institution_id: str, current_admin: dict = Depends(get_current_admin)):
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
#Students (same as superadmin)

@admin_routers.post("/students/upload", status_code=status.HTTP_201_CREATED)
async def admin_upload_students(
    excel_file: UploadFile = File(...),
    certificates: list[UploadFile] = File(default=[]),
    batch_year: str = Form(...),
    institution_id: str = Form(...),
    current_admin: dict = Depends(get_current_admin),
):
    try:
        return await upload_students(
            excel_file=excel_file,
            certificates=certificates,
            batch_year=batch_year,
            principal={"role": "admin", "institution_id": institution_id},
        )
    except HTTPException:
        raise
    except Exception as error:
        raise _internal_server_error(error) from error


def _student_key(value: str) -> str:
    return " ".join(str(value).strip().upper().split())


@admin_routers.get("/students/institution/{institution_name}")
async def admin_get_students_by_institution(
    institution_name: str,
    current_admin: dict = Depends(get_current_admin),
):
    try:
        documents = await students_collections.find({"institution_name": institution_name}).to_list(length=None)
        return get_all_student_documents(documents)
    except Exception as error:
        raise _internal_server_error(error) from error


@admin_routers.get("/students/institution/{institution_name}/year/{year}")
async def admin_get_students_by_year(
    institution_name: str,
    year: int,
    current_admin: dict = Depends(get_current_admin),
):
    try:
        documents = await students_collections.find(
            {"institution_name": institution_name, "month_year_pass": {"$regex": str(year)}}
        ).to_list(length=None)
        return get_all_student_documents(documents)
    except Exception as error:
        raise _internal_server_error(error) from error


@admin_routers.get("/students/institution/{institution_name}/batch/{batch_year}")
async def admin_get_students_by_batch(
    institution_name: str,
    batch_year: str,
    current_admin: dict = Depends(get_current_admin),
):
    try:
        documents = await students_collections.find(
            {"institution_name": institution_name, "batch_year": _student_key(batch_year)}
        ).to_list(length=None)
        return get_all_student_documents(documents)
    except Exception as error:
        raise _internal_server_error(error) from error


@admin_routers.get("/students/stats/{institution_id}")
async def admin_get_student_stats(
    institution_id: str,
    current_admin: dict = Depends(get_current_admin),
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


@admin_routers.get("/students/{roll_no}")
async def admin_get_student(
    roll_no: str,
    current_admin: dict = Depends(get_current_admin),
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


@admin_routers.patch("/students/{roll_no}/certificate", status_code=status.HTTP_200_OK)
async def admin_replace_student_certificate(
    roll_no: str,
    certificate: UploadFile = File(...),
    current_admin: dict = Depends(get_current_admin),
):
    try:
        student_key = _student_key(roll_no)
        existing = await students_collections.find_one({"roll_no": student_key})
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

        await _read_replacement_certificate(certificate)
        certificate_url = upload_student_certificate(
            certificate,
            existing.get("institution_name", ""),
            student_key,
        )
        result = await students_collections.update_one(
            {"student_id": existing["student_id"]},
            {"$set": {"certificate_url": certificate_url}},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

        document = await students_collections.find_one({"student_id": existing["student_id"]})
        return get_single_student_document(document)
    except HTTPException:
        raise
    except Exception as error:
        raise _internal_server_error(error) from error


@admin_routers.patch("/students/{roll_no}")
async def admin_update_student(
    roll_no: str,
    student: UpdateStudents,
    current_admin: dict = Depends(get_current_admin),
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


@admin_routers.delete("/students/{roll_no}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_student(
    roll_no: str,
    current_admin: dict = Depends(get_current_admin),
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
