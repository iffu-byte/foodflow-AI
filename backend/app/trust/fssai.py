"""FSSAI licence number checks.

An FSSAI number has 14 digits: one digit for licence (1) or registration (2),
two for the state code, two for the year, three for the enrolling office and
six for the food business operator. This module checks that structure only.
Whether the licence is active can be confirmed by the customer on the
government FoSCoS portal, which this app links to rather than scrapes.
"""

import re
from datetime import UTC, date, datetime

FOSCOS_URL = "https://foscos.fssai.gov.in/"


def check(license_number: str | None, valid_until: date | None = None) -> dict:
    today = datetime.now(UTC).date()
    if not license_number:
        return {
            "status": "missing",
            "label": "No FSSAI licence on file",
            "number": None,
            "kind": None,
            "valid_until": None,
            "verify_url": FOSCOS_URL,
        }
    digits = re.sub(r"\D", "", license_number)
    problems: list[str] = []
    if len(digits) != 14:
        problems.append("must have 14 digits")
    kind = None
    if digits[:1] == "1":
        kind = "licence"
    elif digits[:1] == "2":
        kind = "registration"
    elif digits:
        problems.append("must start with 1 (licence) or 2 (registration)")
    if len(digits) >= 3 and not 1 <= int(digits[1:3]) <= 38:
        problems.append("state code is out of range")
    if len(digits) >= 5:
        year = int(digits[3:5])
        if year < 6 or year > today.year % 100:
            problems.append("year of issue is not plausible")

    expired = valid_until is not None and valid_until < today
    if problems:
        status, label = "invalid", "Licence number looks wrong: " + "; ".join(problems)
    elif expired:
        status, label = "expired", f"Licence expired on {valid_until.isoformat()}"
    else:
        status = "format_ok"
        label = (
            "Licence number format is valid"
            + (f", valid until {valid_until.isoformat()}" if valid_until else "")
            + ". Confirm it is active on FoSCoS."
        )
    return {
        "status": status,
        "label": label,
        "number": digits or license_number,
        "kind": kind,
        "valid_until": valid_until.isoformat() if valid_until else None,
        "verify_url": FOSCOS_URL,
    }
