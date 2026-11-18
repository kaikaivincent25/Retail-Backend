import re


def normalize_customer_phone(phone: str | None) -> str | None:
    if not phone:
        return None

    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10 and digits.startswith("0"):
        digits = f"254{digits[1:]}"
    elif len(digits) == 9 and digits.startswith(("7", "1")):
        digits = f"254{digits}"

    if not 9 <= len(digits) <= 15 or digits.startswith("0"):
        return None
    return digits
