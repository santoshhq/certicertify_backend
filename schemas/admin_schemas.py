DEFAULT_PERMISSIONS = {
    "students_view": False,
    "students_create": False,
    "students_update": False,
    "students_delete": False,
    "institutions_view": False,
    "institutions_create": False,
    "institutions_update": False,
    "institutions_delete": False,
}


def single_admin_doc(document):
    return {
        "admin_id":document.get("admin_id"),
        "admin_loginId":document.get("admin_loginId"),
        "admin_name":document.get("admin_name"),
        "email":document.get("email"),
        "mobilenumber":document.get("mobilenumber"),
        "password":document.get("password"),
        "superadmin_id":document.get("superadmin_id"),
        "role":document.get("role"),
        "access_level": document.get("access_level") or "custom",
        "permissions": {**DEFAULT_PERMISSIONS, **(document.get("permissions") or {})},
        "status": document.get("status", True),
    }

def get_all_admin_doc(documents):
    return [single_admin_doc(x) for x in documents]
