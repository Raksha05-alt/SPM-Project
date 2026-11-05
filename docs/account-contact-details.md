# Own account contact details (SCRUM-2, side lane ACCOUNT)

Every signed-in user can see their account (name, role, organisation, email) and change their **own** name and email address. Nothing else about an account can change here.

## API: `/api/auth/me/` (the caller's own account only; there is no user id)

| Method | Behaviour |
| --- | --- |
| `GET` | AC1: id, email, first and last name, role and its label, organisation and its name, landing path |
| `PATCH` | AC2: saves the allowed fields and returns the account plus `changed_fields`. A save that changes nothing records nothing. |
| `PUT`, other methods | 405 |

**Allowlist** (`apps/accounts/account.py`): `first_name`, `last_name`, `email`.
- **Required (AC4):** first name and email. A blank or whitespace-only value returns 400 naming the field, with `missing_fields`. Every problem is reported at once. Last name is optional, because single names exist.
- **Email:** checked for format (Django `validate_email`), domain lower-cased as for new accounts, and a **case-insensitive** duplicate check against other accounts. A clash is refused rather than merged.
- **Anything else (AC3)** returns **403** with `refused_fields`, with nothing saved (not even the allowed fields in the same request), and is audited as refused. That covers role, organisation, staff and superuser flags, `is_active`, username, coordinator availability, password and id. The refusal is recorded before the save transaction, so the audit entry survives.
- A successful change is audited ("Changed: …") in the same transaction as the save.

## Sign-in, sessions and notifications

- Email is the sign-in identifier (`USERNAME_FIELD`). After a change, the **current session continues**; the next sign-in uses the new address, and the old one is refused (`test_ac2b`).
- In-app notices go to the account, not the address, so they keep arriving after a change (`test_ac2d`). Messages and contact displays written afterwards use the saved details. For example, a coordinator's next assignment notice and the event's `coordinator_email` show the new address, while earlier notices keep their original text (`test_ac2c`). No email provider or phone field is added.

## Web

- **`/account`** (`web/src/pages/AccountPage.tsx`), for any signed-in user.
  - A read-only summary shows name, role, organisation (or "ConnectSphere" for staff) and email.
  - A form edits first name, last name and email. It sends only the fields that changed and shows each field's error beside it.
  - After a save, it says when the email changed: "Sign in with your new email address next time."
- **Header:** the user's name is now a link to `/account`. After a save, `AuthContext.updateUser` refreshes it without signing in again.

## Test evidence (agent run, 5 November 2026 — not a teammate review)

| Check | Result |
| --- | --- |
| `apps/accounts/tests/test_scrum_2_account_details.py` | 32 passed (real `/api/auth/login/` sessions). `account.py` has 100% statement and branch coverage. |
| Full backend suite (PostgreSQL 16) | 1857 passed; total coverage 99.50% |
| Web: lint, vitest with CI coverage, build | Clean; 418 passed. `AccountPage.tsx`, `AuthProvider.tsx` and `Layout.tsx` 100% lines (`Layout` was previously untested). |
| Playwright, all 18 journeys, `--workers=1 --retries=0` | 18 passed |
| Browser check | The organiser opened `/account` from the header. A blank email was refused with "Email address is required.". Saving "Adaline" and adaline@acme.example updated the header immediately. A role change through the API returned 403 `refused_fields: ["role"]`. After signing out, the old email was refused and the new one signed in. |

Still to do: a teammate correctness review and a manual check with demo data.
