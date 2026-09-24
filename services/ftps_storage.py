import os
import re
import logging
from io import BytesIO
from ftplib import FTP_TLS, error_perm
from pathlib import PurePosixPath
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, unquote

from dotenv import load_dotenv
from fastapi import HTTPException

from services.file_compression import compress_if_needed

load_dotenv()

logger = logging.getLogger(__name__)


# ============================================================
# Configuration
# ============================================================

FTPS_HOST = os.getenv("FTPS_HOST", "ftp.certicertify.com")
FTPS_PORT = int(os.getenv("FTPS_PORT", "21"))
FTPS_USERNAME = os.getenv("FTPS_USERNAME")
FTPS_PASSWORD = os.getenv("FTPS_PASSWORD")

# FTP root is already:
# /home/certicertify/certicertify_storage
#
# Therefore use paths relative to that root.
FTPS_BASE_DIR = os.getenv("FTPS_BASE_DIR", "/institutions")


# Thread pool because ftplib is synchronous
_executor = ThreadPoolExecutor(max_workers=10)


# ============================================================
# FTP Connection
# ============================================================

def _connect() -> FTP_TLS:
    """
    Create and authenticate an FTPS connection.
    """

    if not FTPS_USERNAME:
        raise RuntimeError("FTPS_USERNAME is not configured")

    if not FTPS_PASSWORD:
        raise RuntimeError("FTPS_PASSWORD is not configured")

    ftps = FTP_TLS()

    ftps.connect(
        host=FTPS_HOST,
        port=FTPS_PORT,
        timeout=30
    )

    ftps.login(
        user=FTPS_USERNAME,
        passwd=FTPS_PASSWORD
    )

    # Enable TLS protection for data transfer
    ftps.prot_p()

    return ftps


def _close(ftps: FTP_TLS):
    """
    Safely close FTPS connection.
    """

    try:
        ftps.quit()
    except Exception:
        try:
            ftps.close()
        except Exception:
            pass


# ============================================================
# Path Security
# ============================================================

def _safe_path(path: str) -> str:
    """
    Prevent directory traversal such as ../
    """

    path = path.replace("\\", "/").strip("/")

    if ".." in PurePosixPath(path).parts:
        raise ValueError("Invalid storage path")

    if not path:
        raise ValueError("Storage path cannot be empty")

    return f"{FTPS_BASE_DIR.rstrip('/')}/{path}"


# ============================================================
# Directory Creation
# ============================================================

def _ensure_directory(ftps: FTP_TLS, directory: str):
    """
    Create directories recursively if they don't exist.
    """

    parts = directory.strip("/").split("/")

    current = ""

    for part in parts:

        current += "/" + part

        try:
            ftps.cwd(current)

        except error_perm:

            # Go back to root of FTP account
            ftps.cwd("/")

            try:
                ftps.mkd(current)
            except error_perm:
                # Directory may have been created concurrently
                pass

            ftps.cwd(current)


# ============================================================
# Upload
# ============================================================

def _upload_file_sync(
    file_data: bytes,
    remote_path: str,
    content_type: str | None = None
) -> str:

    ftps = None

    try:

        ftps = _connect()

        full_path = _safe_path(remote_path)

        directory = str(PurePosixPath(full_path).parent)
        filename = PurePosixPath(full_path).name

        # Create directory if required
        _ensure_directory(ftps, directory)

        # Upload file
        with BytesIO(file_data) as file:

            ftps.storbinary(
                f"STOR {filename}",
                file
            )

        return full_path

    finally:

        if ftps:
            _close(ftps)


async def upload_file(
    file_data: bytes,
    remote_path: str,
    content_type: str | None = None
) -> str:
    """
    Upload bytes to cPanel FTPS.

    Example:

        path = await upload_file(
            pdf_bytes,
            "abc123/certificate.pdf"
        )
    """

    loop = __import__("asyncio").get_running_loop()

    return await loop.run_in_executor(
        _executor,
        _upload_file_sync,
        file_data,
        remote_path,
        content_type
    )


# ============================================================
# Download
# ============================================================

def _download_file_sync(remote_path: str) -> bytes:

    ftps = None

    try:

        ftps = _connect()

        full_path = _safe_path(remote_path)

        directory = str(PurePosixPath(full_path).parent)
        filename = PurePosixPath(full_path).name

        ftps.cwd(directory)

        buffer = BytesIO()

        ftps.retrbinary(
            f"RETR {filename}",
            buffer.write
        )

        return buffer.getvalue()

    finally:

        if ftps:
            _close(ftps)


async def download_file(remote_path: str) -> bytes:
    """
    Download a file from FTPS.

    Returns:
        bytes
    """

    loop = __import__("asyncio").get_running_loop()

    return await loop.run_in_executor(
        _executor,
        _download_file_sync,
        remote_path
    )


# ============================================================
# Delete
# ============================================================

def _delete_file_sync(remote_path: str) -> bool:

    ftps = None

    try:

        ftps = _connect()

        full_path = _safe_path(remote_path)

        directory = str(PurePosixPath(full_path).parent)
        filename = PurePosixPath(full_path).name

        ftps.cwd(directory)

        ftps.delete(filename)

        return True

    except error_perm as e:

        # File does not exist
        if "550" in str(e):
            return False

        raise

    finally:

        if ftps:
            _close(ftps)


async def delete_file(remote_path: str) -> bool:
    """
    Delete a file from FTPS.
    """

    loop = __import__("asyncio").get_running_loop()

    return await loop.run_in_executor(
        _executor,
        _delete_file_sync,
        remote_path
    )


# ============================================================
# Check File Exists
# ============================================================

def _file_exists_sync(remote_path: str) -> bool:

    ftps = None

    try:

        ftps = _connect()

        full_path = _safe_path(remote_path)

        directory = str(PurePosixPath(full_path).parent)
        filename = PurePosixPath(full_path).name

        ftps.cwd(directory)

        try:

            ftps.size(filename)
            return True

        except error_perm:

            return False

    finally:

        if ftps:
            _close(ftps)


async def file_exists(remote_path: str) -> bool:
    """
    Check whether a file exists.
    """

    loop = __import__("asyncio").get_running_loop()

    return await loop.run_in_executor(
        _executor,
        _file_exists_sync,
        remote_path
    )


# ============================================================
# Get File URL / Path
# ============================================================

def get_storage_path(remote_path: str) -> str:
    """
    Return the internal FTPS storage path.

    Example:

        institutions/123/certificate.pdf

    becomes:

        /institutions/123/certificate.pdf
    """

    return _safe_path(remote_path)

# ============================================================
# Student Certificates
# ============================================================
#
# Replaces services.aws_s3.upload_student_certificate.
#
# Stored at:
#
#     /institutions/<institution_name>/<batch_year>/<course>/<original_filename>
#
# and the public URL returned (saved in MongoDB as certificate_url) is:
#
#     <FTPS_PUBLIC_BASE_URL>/institutions/<institution_name>/<batch_year>/<course>/<original_filename>
#
# The storage folder is not web-accessible, so by default files are served by
# this backend's /files route (routers/files_router.py). In production set
# FTPS_PUBLIC_BASE_URL=https://<your-backend-domain>/files

FTPS_PUBLIC_BASE_URL = os.getenv("FTPS_PUBLIC_BASE_URL", "http://127.0.0.1:5959/files").rstrip("/")

ALLOWED_CERTIFICATE_EXTENSIONS = {"pdf", "jpg", "jpeg"}


def _folder_name(value: str) -> str:
    """
    Make a value safe to use as a single folder / file name while
    keeping it readable: "MLR Institute / CSE" -> "MLR_Institute_CSE".
    """

    name = re.sub(r"[^A-Za-z0-9._&()-]+", "_", str(value or "").strip()).strip("._")
    return name or "unknown"


def _public_url(full_path: str) -> str:
    return f"{FTPS_PUBLIC_BASE_URL}{quote(full_path)}"


def _full_path_from_url(certificate_url: str | None) -> str | None:
    """
    Reverse of _public_url. Returns None for URLs that are not on
    FTPS storage (e.g. old S3 URLs).
    """

    if not certificate_url or not FTPS_PUBLIC_BASE_URL:
        return None

    if not certificate_url.startswith(FTPS_PUBLIC_BASE_URL + "/"):
        return None

    full_path = unquote(certificate_url[len(FTPS_PUBLIC_BASE_URL):])

    base_dir = FTPS_BASE_DIR.rstrip("/") + "/"
    if not full_path.startswith(base_dir):
        return None

    # Re-validate (blocks ../ tricks)
    return _safe_path(full_path[len(base_dir):])


def _remote_exists(ftps: FTP_TLS, filename: str) -> bool:
    try:
        ftps.voidcmd("TYPE I")
        ftps.size(filename)
        return True
    except error_perm:
        return False


def upload_student_certificate(
    file,
    institution_name: str,
    batch_year: str,
    course: str,
    roll_no: str,
    replacing_url: str | None = None,
) -> str:
    """
    Upload a student's certificate (PDF or JPG) to cPanel FTPS, compressing
    it to ~150 KB first if it is larger than 200 KB.

    `file` is an UploadFile (or anything with .filename, .file).

    `replacing_url` is the student's current certificate_url when replacing
    a certificate; the new file may then overwrite that same path. After the
    DB is updated, call delete_certificate_by_url(old_url) to remove the old
    file if the URL changed.

    Returns the certificate's public URL.
    """

    if not FTPS_PUBLIC_BASE_URL:
        raise HTTPException(
            status_code=500,
            detail="Failed to upload certificate: FTPS_PUBLIC_BASE_URL is not configured"
        )

    original_name = PurePosixPath((file.filename or "").replace("\\", "/")).name
    stem, _, extension = original_name.rpartition(".")
    extension = extension.lower()

    if not stem or extension not in ALLOWED_CERTIFICATE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only PDF and JPG certificates are allowed."
        )

    file.file.seek(0)
    data = compress_if_needed(file.file.read(), extension)

    folder = "/".join(
        _folder_name(part) for part in (institution_name, batch_year, course)
    )
    filename = f"{_folder_name(stem)}.{extension}"

    replacing_path = _full_path_from_url(replacing_url)

    ftps = None

    try:
        ftps = _connect()

        full_path = _safe_path(f"{folder}/{filename}")
        _ensure_directory(ftps, str(PurePosixPath(full_path).parent))

        # Never overwrite another student's certificate that happens to
        # have the same original filename in this folder.
        if full_path != replacing_path and _remote_exists(ftps, filename):
            filename = f"{_folder_name(stem)}_{_folder_name(roll_no)}.{extension}"
            full_path = _safe_path(f"{folder}/{filename}")

        with BytesIO(data) as buffer:
            ftps.storbinary(f"STOR {filename}", buffer)

        return _public_url(full_path)

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload certificate: {str(e)}"
        )

    finally:
        if ftps:
            _close(ftps)


def delete_certificate_by_url(certificate_url: str | None) -> bool:
    """
    Delete a certificate previously uploaded by upload_student_certificate.
    Non-FTPS URLs (e.g. old S3 ones) are ignored. Never raises: a failed
    cleanup must not fail the request.
    """

    full_path = _full_path_from_url(certificate_url)
    if full_path is None:
        return False

    ftps = None

    try:
        ftps = _connect()
        ftps.cwd(str(PurePosixPath(full_path).parent))
        ftps.delete(PurePosixPath(full_path).name)
        return True

    except Exception as e:
        logger.warning("Could not delete old certificate %s: %s", full_path, e)
        return False

    finally:
        if ftps:
            _close(ftps)
