
def get_single_document(document):
    if document is None:
        return None

    return {
        "student_id": document.get("student_id"),
        "institution_id": document.get("institution_id"),
        "institution_name": document.get("institution_name"),
        "certificate_no":document.get("certificate_no"),
        "roll_no": document.get("roll_no"),
        "student_name": document.get("student_name"),
        "surname_lastName": document.get("surname_lastName"),
        "course_or_Acadamic": document.get("course_or_Acadamic"),
        "month_year_pass": document.get("month_year_pass"),
        "grade": document.get("grade"),
        "batch_year":document.get("batch_year"),
        "certificate_url": document.get("certificate_url"),
        "certificate_id": document.get("certificate_id"),
    }

def get_all_documents(documents):
    return [get_single_document(document) for document in documents]
