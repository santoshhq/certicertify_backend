import os
import re
import uuid
import boto3
from botocore.exceptions import ClientError
from fastapi import UploadFile, HTTPException


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
    return slug.lower() or "unknown"


# ============================================================
# 1. CORE S3 CONNECTION
# ============================================================

def get_s3_client():
    """
    Create and return an AWS S3 client.
    """

    return boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


# ============================================================
# 2. UPLOAD LOGO
# ============================================================

def upload_logo(file: UploadFile):
    """
    Upload only logo images to:

        logos/<unique_filename>

    Allowed:
        JPG
        JPEG
        PNG
        WEBP
    """

    allowed_types = {
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Only JPG, JPEG, PNG and WEBP images are allowed."
        )

    # Get extension
    extension = file.filename.split(".")[-1].lower()

    # Generate unique filename
    filename = f"{uuid.uuid4()}.{extension}"

    # S3 path
    s3_key = f"logos/{filename}"

    s3 = get_s3_client()

    try:
        s3.upload_fileobj(
            file.file,
            os.getenv("AWS_S3_BUCKET"),
            s3_key,
            ExtraArgs={
                "ContentType": file.content_type,
            },
        )

        return {
            "filename": filename,
            "s3_key": s3_key,
            "content_type": file.content_type,
        }

    except ClientError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload logo: {str(e)}"
        )


# ============================================================
# 3. UPLOAD CERTIFICATE
# ============================================================

def upload_certificate(file: UploadFile):
    """
    Upload only PDF certificates to:

        certificates/<unique_filename>
    """

    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="Only PDF certificates are allowed."
        )

    # Generate unique filename
    filename = f"{uuid.uuid4()}.pdf"

    # S3 path
    s3_key = f"certificates/{filename}"

    s3 = get_s3_client()

    try:
        s3.upload_fileobj(
            file.file,
            os.getenv("AWS_S3_BUCKET"),
            s3_key,
            ExtraArgs={
                "ContentType": "application/pdf",
            },
        )

        return {
            "filename": filename,
            "s3_key": s3_key,
            "content_type": "application/pdf",
        }

    except ClientError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload certificate: {str(e)}"
        )


# ============================================================
# 4. UPLOAD STUDENT CERTIFICATE
# ============================================================

def upload_student_certificate(file: UploadFile, institution_name: str, roll_no: str) -> str:
    """
    Upload a student's certificate (PDF or JPG) to:

        certificates/<institution_name>_<roll_no>.<ext>

    Returns the certificate's public S3 URL.
    """

    allowed_extensions = {"pdf", "jpg", "jpeg"}
    extension = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""

    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail="Only PDF and JPG certificates are allowed."
        )

    filename = f"{_slugify(institution_name)}_{_slugify(roll_no)}.{extension}"
    s3_key = f"certificates/{filename}"

    bucket = os.getenv("AWS_S3_BUCKET")
    s3 = get_s3_client()

    try:
        s3.upload_fileobj(
            file.file,
            bucket,
            s3_key,
            ExtraArgs={
                "ContentType": file.content_type or "application/octet-stream",
            },
        )

        return f"https://{bucket}.s3.{os.getenv('AWS_REGION')}.amazonaws.com/{s3_key}"

    except ClientError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload certificate: {str(e)}"
        )