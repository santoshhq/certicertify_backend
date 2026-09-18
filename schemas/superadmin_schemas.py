def  single_document(document):
    return{
            "superadmin_id":document.get("superadmin_id"),
            "unique_id":document.get("unique_id"),
            "fullname":document.get("fullname"),
            "email":document.get("email"),
            "mobilenumber":document.get("mobilenumber"),
            "password":document.get("password"),
            "otp_verified":document.get("otp_verified", False),
            }

def get_all_superadmins_details(documents):
    return [single_document(x) for x in documents ]