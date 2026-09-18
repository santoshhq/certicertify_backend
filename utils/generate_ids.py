import string
import secrets


def generate_superadmin_id(val:int) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(val))

def generate_id(val:int) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(val))


def generate_numeric_id(length: int) -> str:
    if length <= 0:
        raise ValueError("length must be greater than 0")

    return "".join(secrets.choice(string.digits) for _ in range(length))