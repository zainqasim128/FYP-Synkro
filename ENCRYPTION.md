# Database Encryption — Synkro

## Overview

Synkro uses **application-level (column-level) Fernet encryption** to protect sensitive credentials stored in the database. This works identically whether the database is Neon (cloud PostgreSQL) or a local PostgreSQL instance — the encryption happens in Python before anything touches the database.

---

## What Is Encrypted

Not the entire database. Only the `integrations` table columns that hold real credentials:

| Integration     | Encrypted Field(s)                          |
|-----------------|---------------------------------------------|
| Gmail           | `access_token` (App Password)               |
| Slack           | `access_token` (bot token), `platform_metadata.user_access_token` |
| Jira            | `access_token` (API token)                  |
| Google Calendar | `access_token`, `refresh_token`             |

Everything else — task titles, meeting transcripts, user emails, messages — is stored as plain text. Those are not credentials and do not need encryption.

---

## How It Works — Step by Step

### Algorithm: Fernet (AES-128-CBC + HMAC-SHA256)

Fernet is a standard from Python's `cryptography` library. Every encrypted value is:
1. **Encrypted** with AES-128-CBC so the content is unreadable
2. **Signed** with HMAC-SHA256 so any tampering is detectable

### Saving a credential (encrypt on write)

When a user connects Gmail with their App Password:

```
"my-app-password"
        │
        ▼  encrypt_value()  [backend/app/utils/security.py]
        │
"gAAAAABnx8K2mP9Xk...long unreadable string..."
        │
        ▼
  saved to integrations.access_token in the database
```

### Reading a credential (decrypt on read)

When the app needs to fetch emails via IMAP:

```
"gAAAAABnx8K2mP9Xk...long unreadable string..."   (read from DB)
        │
        ▼  decrypt_value()  [backend/app/utils/security.py]
        │
"my-app-password"
        │
        ▼
  used for IMAP connection
```

---

## The Encryption Key

The key that encrypts and decrypts everything is `FERNET_KEY` in `backend/.env`:

```
FERNET_KEY=XC4O_hlC2-gSWFZgq7YMNmBCpletk5lq2UaYxmIM8bU=
```

**This key never enters the database.** It lives only in the `.env` file on the server. If someone steals a full database dump, they see:

```
access_token: gAAAAABnx8K2mP9Xk...completely unreadable
```

Without `FERNET_KEY`, that string is cryptographically useless.

---

## Why FERNET_KEY Is Separate from SECRET_KEY

The app has two secrets with different jobs:

| Key          | Purpose                          |
|--------------|----------------------------------|
| `SECRET_KEY` | Signs JWT login tokens           |
| `FERNET_KEY` | Encrypts DB credentials at rest  |

Keeping them separate means:
- Rotating `SECRET_KEY` (which logs all users out) does **not** break stored tokens
- Rotating `FERNET_KEY` (re-encryption event) does **not** affect JWT sessions
- A compromise of one key does not expose the other layer

---

## Plaintext Fallback in decrypt_value

`decrypt_value()` in `security.py` has intentional fallback logic:

```python
try:
    return _fernet.decrypt(cipher.encode()).decode()
except InvalidToken:
    return cipher  # stored as plaintext — return as-is
```

**Why this exists:** Before encryption was added, some rows (e.g. Gmail passwords) were saved as plaintext. Rather than requiring a database migration script, this fallback lets those old rows keep working. The next time the user reconnects their integration, the new value is saved encrypted, and the fallback never triggers again.

This is safe because a legitimate Fernet ciphertext will never accidentally pass as plaintext — the HMAC signature check catches any mismatch.

---

## Neon (Cloud) vs Local PostgreSQL

No difference whatsoever. The flow is:

```
Python app  →  encrypt_value()  →  database (Neon or local)
Python app  ←  decrypt_value()  ←  database (Neon or local)
```

The database stores an opaque string. It does not know or care whether that string is encrypted or what algorithm was used. To switch from Neon to local PostgreSQL:

1. Change `DATABASE_URL` in `.env` to point to localhost
2. Keep `FERNET_KEY` the same (same key = same encryption = all tokens still work)
3. No code changes, no re-encryption needed

---

## What This Protects Against

| Threat                                         | Protected |
|------------------------------------------------|-----------|
| Someone gets a full database dump or backup    | Yes       |
| Someone reads the DB via SQL injection         | Yes       |
| Someone browses the Neon dashboard             | Yes       |
| Someone reads DB logs or query history         | Yes       |
| Someone gets the `.env` file                   | No — they have the key |
| Someone gets full server/OS access             | No — same as above     |

The last two are unavoidable for any system. You protect `.env` the same way you protect a master password. It must never be committed to git (already in `.gitignore`).

---

## Critical Rule: Never Change FERNET_KEY After Data Is Saved

`FERNET_KEY` must stay stable for the lifetime of the data it encrypted. If you generate a new key:
- All previously encrypted tokens become permanently unreadable
- Every user would need to reconnect all their integrations

The only correct way to rotate the key is a **re-encryption migration**: read every encrypted value, decrypt with the old key, re-encrypt with the new key, save. This is a deliberate maintenance operation, not something to do casually.

---

## Key Files

| File | Role |
|------|------|
| `backend/.env` | Stores `FERNET_KEY` (never commit to git) |
| `backend/app/config.py` | Loads `FERNET_KEY` via Pydantic Settings |
| `backend/app/utils/security.py` | `encrypt_value()` and `decrypt_value()` implementation |
| `backend/app/routers/integrations.py` | Calls encrypt on save, decrypt on read for all integrations |
| `backend/app/services/slack_service.py` | Calls `decrypt_value` before using Slack token |
| `backend/app/services/jira_service.py` | Calls `decrypt_value` before using Jira token |
| `backend/app/services/google_calendar_service.py` | Calls `decrypt_value` before using GCal tokens |
