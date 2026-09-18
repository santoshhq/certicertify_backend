def single_admin_doc(document):
    return {
        "admin_id":document.get("admin_id"),
        "admin_loginId":document.get("admin_loginId"),
        "admin_name":document.get("admin_name"),
        "email":document.get("email"),
        "mobilenumber":document.get("mobilenumber"),
        "password":document.get("password"),
        "superadmin_id":document.get("superadmin_id"),
        "role":document.get("role")
    }
    
def get_all_admin_doc(documents):
    return [single_admin_doc(x) for x in documents]