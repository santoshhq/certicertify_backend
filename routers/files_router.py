from ftplib import error_perm

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from services.ftps_storage import FTPS_BASE_DIR, download_file


files_router = APIRouter(prefix="/files", tags=["Files"])

CONTENT_TYPES = {
	"pdf": "application/pdf",
	"jpg": "image/jpeg",
	"jpeg": "image/jpeg",
}


@files_router.get("/{file_path:path}")
async def get_file(file_path: str):
	"""
	Serve a certificate stored on cPanel FTPS. certificate_url values saved in
	MongoDB point here (FTPS_PUBLIC_BASE_URL = <backend>/files), the same way
	they used to point at the public S3 object.
	"""
	base_dir = FTPS_BASE_DIR.strip("/") + "/"
	extension = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
	if not file_path.startswith(base_dir) or extension not in CONTENT_TYPES:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

	try:
		content = await download_file(file_path[len(base_dir):])
	except ValueError as error:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from error
	except error_perm as error:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from error

	return Response(
		content=content,
		media_type=CONTENT_TYPES[extension],
		headers={
			"Content-Disposition": "inline",
			"Cache-Control": "public, max-age=3600",
		},
	)
