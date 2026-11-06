"""SCRUM-2 - a signed-in user maintains their own contact details.

Only the fields in ``EDITABLE_FIELDS`` can change, and only on the caller's
own account (the endpoint is /api/auth/me/, with no user id to target).
Anything else in the request - role, organisation, staff flags, username,
availability, password - is refused as a whole, with nothing saved, and the
attempt is written to the audit log (AC3).

Email is the sign-in identifier (``User.USERNAME_FIELD``) and the contact
address shown to others, for example as an event's coordinator contact. A
change keeps the current session; the next sign-in uses the new address.
In-app notices go to the account, not the address, so they keep arriving;
messages written after the change quote the new details (AC2).
"""

from django.contrib.auth.base_user import BaseUserManager
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction

from apps.accounts.models import User
from apps.core.audit import record, record_denied

EDITABLE_FIELDS = ("first_name", "last_name", "email")
# AC4 - required contact fields; a last name is optional (single names exist).
REQUIRED_FIELDS = ("first_name", "email")
LABELS = {"first_name": "First name", "last_name": "Last name", "email": "Email address"}
MAX_NAME = User._meta.get_field("first_name").max_length


class AccountChangeRefused(Exception):
    """The request tried to change something other than the caller's contact details."""

    def __init__(self, fields: list[str]):
        self.fields = fields
        super().__init__(f"Refused fields: {', '.join(fields)}")


class AccountDetailsInvalid(Exception):
    """Every invalid or missing field, by name. Nothing was saved."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def _clean(user: User, data: dict) -> dict:
    cleaned, errors = {}, {}
    for name in EDITABLE_FIELDS:
        if name not in data:
            continue
        value = data[name]
        if value is None:
            value = ""
        if not isinstance(value, str):
            errors[name] = f"{LABELS[name]} must be text."
            continue
        value = value.strip()
        if name in REQUIRED_FIELDS and not value:
            errors[name] = f"{LABELS[name]} is required."
            continue
        if name == "email":
            value = BaseUserManager.normalize_email(value)
            if len(value) > User._meta.get_field("email").max_length:
                errors[name] = "Email address is too long."
                continue
            try:
                validate_email(value)
            except DjangoValidationError:
                errors[name] = "Enter a valid email address."
                continue
            if User.objects.filter(email__iexact=value).exclude(pk=user.pk).exists():
                errors[name] = "Another account already uses this email address."
                continue
        elif len(value) > MAX_NAME:
            errors[name] = f"{LABELS[name]} must be at most {MAX_NAME} characters."
            continue
        cleaned[name] = value
    if errors:
        raise AccountDetailsInvalid(errors)
    return cleaned


def update_own_details(user: User, data, *, action: str) -> tuple[User, list[str]]:
    """Save the caller's own contact details; return the user and changed fields.

    Raises AccountChangeRefused (nothing saved, audited) for any field outside
    the allowlist, and AccountDetailsInvalid naming every bad field (AC4).
    """
    if not isinstance(data, dict):
        raise AccountDetailsInvalid({"non_field_errors": "Send the details to change."})
    refused = sorted(key for key in data if key not in EDITABLE_FIELDS)
    if refused:
        record_denied(
            user,
            action=action,
            obj=user,
            detail="own account: cannot change " + ", ".join(refused),
        )
        # Refused before the transaction, so the audit record of the attempt stays.
        raise AccountChangeRefused(refused)
    return _save(user, data, action=action)


@transaction.atomic
def _save(user: User, data: dict, *, action: str) -> tuple[User, list[str]]:
    locked = User.objects.select_for_update().get(pk=user.pk)
    cleaned = _clean(locked, data)
    changed = [name for name, value in cleaned.items() if getattr(locked, name) != value]
    if changed:
        for name in changed:
            setattr(locked, name, cleaned[name])
        locked.save(update_fields=changed)
        record(
            locked, action=action, allowed=True, obj=locked, detail="Changed: " + ", ".join(changed)
        )
    return locked, changed
