
def get_single_document(document):
    if document is None:
        return None

    return {
        "institution_id": document.get("institution_id"),
        "name": document.get("name"),
        "email_id": document.get("email_id"),
        "institution_name": document.get("institution_name"),
        "postal_code": document.get("postal_code"),
        "city": document.get("city"),
        "state": document.get("state"),
        "country": document.get("country"),
        "mobile_no": document.get("mobile_no"),
        "otp_verified": document.get("otp_verified", False),
    }

def get_all_documents(documents):
    return [get_single_document(document) for document in documents]
