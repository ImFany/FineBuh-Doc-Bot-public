"""
Utilities for masking sensitive data in logs.
Protects PII (personal identifiable information) and financial data.
"""
import re
from typing import Any, Dict


def mask_account_number(account: str) -> str:
    """Mask bank account number, showing only last 4 digits."""
    if not account or len(account) < 4:
        return "****"
    return "*" * (len(account) - 4) + account[-4:]


def mask_inn(inn: str) -> str:
    """Mask INN (tax ID), showing only last 2 digits."""
    if not inn or len(inn) < 2:
        return "****"
    return "*" * (len(inn) - 2) + inn[-2:]


def mask_phone(phone: str) -> str:
    """Mask phone number, showing only last 3 digits."""
    if not phone or len(phone) < 3:
        return "****"
    return "*" * (len(phone) - 3) + phone[-3:]


def mask_email(email: str) -> str:
    """Mask email, showing only domain."""
    if "@" not in email:
        return "***@***"
    local, domain = email.split("@", 1)
    return "*" * max(1, len(local) - 2) + local[-2:] + "@" + domain


def mask_buyer_dict(buyer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a masked copy of buyer data for logging.
    Masks: INN, КПП, bank account numbers, director name.
    """
    if not buyer:
        return {}

    masked = buyer.copy()

    # Mask INN
    if "inn" in masked and masked["inn"]:
        masked["inn"] = mask_inn(masked["inn"])

    # Mask КПП
    if "kpp" in masked and masked["kpp"]:
        masked["kpp"] = mask_account_number(masked["kpp"])

    # Mask расчётный счёт (Р/С)
    if "rs" in masked and masked["rs"]:
        masked["rs"] = mask_account_number(masked["rs"])

    # Mask корр. счёт (К/С)
    if "ks" in masked and masked["ks"]:
        masked["ks"] = mask_account_number(masked["ks"])

    # Mask БИК
    if "bik" in masked and masked["bik"]:
        masked["bik"] = mask_account_number(masked["bik"])

    # Mask director name (leave only initials)
    if "director" in masked and masked["director"]:
        director = masked["director"].strip()
        parts = director.split()
        if len(parts) > 0:
            # Show first letter of first name + surname
            masked["director"] = parts[-1] + " " + parts[0][0] + "."
        else:
            masked["director"] = "****"

    # Mask address (show only region and city)
    if "address" in masked and masked["address"]:
        # Keep only first part (region + city)
        address_parts = masked["address"].split(",")
        masked["address"] = address_parts[0] if address_parts else "***"

    return masked


def mask_text(text: str) -> str:
    """
    Basic text masking: replaces potential account numbers with asterisks.
    Matches 20-digit patterns (typical Russian account numbers).
    """
    # Match 20-digit account numbers
    text = re.sub(r"\b\d{20}\b", "***", text)
    # Match 10-12 digit INNs
    text = re.sub(r"\b(\d{10}|\d{12})\b", "****", text)
    return text


def format_buyer_for_log(buyer: Dict[str, Any]) -> str:
    """Format buyer data for logging with masked sensitive fields."""
    masked = mask_buyer_dict(buyer)
    return f"INN={masked.get('inn', 'N/A')}, Name={masked.get('name', 'N/A')}, Director={masked.get('director', 'N/A')}"
