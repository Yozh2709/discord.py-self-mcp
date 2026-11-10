"""Named credentials, encrypted for the current Windows user with DPAPI."""

import base64
import json
import os
from pathlib import Path
import re
import tempfile


class AccountError(ValueError):
    """An account error whose message is safe to return through MCP."""


def account_name(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,47}", value):
        raise AccountError("account must be 1-48 letters, digits, dots, underscores or hyphens")
    return value.lower()


def validate_token(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value.strip()):
        raise AccountError("A non-empty Discord user token is required")
    return value.strip()


def _protect(value: bytes) -> bytes:
    if os.name != "nt":
        raise AccountError("Saved accounts require Windows DPAPI on this build")
    import win32crypt
    return win32crypt.CryptProtectData(value, "Discord MCP account", None, None, None, 0)


def _unprotect(value: bytes) -> bytes:
    if os.name != "nt":
        raise AccountError("Saved accounts require Windows DPAPI on this build")
    import win32crypt
    return win32crypt.CryptUnprotectData(value, None, None, None, 0)[1]


class AccountStore:
    def __init__(self, path=None, *, protect=None, unprotect=None):
        self.path = Path(path) if path else Path(
            os.getenv("DISCORD_ACCOUNTS_FILE")
            or Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "discord-self-mcp" / "accounts.json"
        )
        self._protect = protect or _protect
        self._unprotect = unprotect or _unprotect

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "active_account": None, "accounts": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            assert data["version"] == 1 and isinstance(data["accounts"], dict)
            active = data["active_account"]
            assert active is None or active in data["accounts"]
            for name, row in data["accounts"].items():
                assert account_name(name) == name
                assert isinstance(row["credential"], str)
                assert isinstance(row["user_id"], str) and row["user_id"].isascii() and row["user_id"].isdigit()
                assert isinstance(row["username"], str) and isinstance(row["display_name"], str)
            return data
        except Exception:
            raise AccountError("Cannot read the saved account file; check its format and permissions") from None

    def _write(self, data):
        temp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp = tempfile.mkstemp(prefix=".accounts-", dir=self.path.parent)
            with os.fdopen(descriptor, "w", encoding="utf-8") as target:
                os.chmod(temp, 0o600)
                json.dump(data, target, ensure_ascii=False, indent=2)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp, self.path)
        except Exception:
            raise AccountError("Cannot write the encrypted account file") from None
        finally:
            if temp and Path(temp).exists():
                Path(temp).unlink()

    def selected(self):
        return self._read()["active_account"]

    def list_accounts(self):
        return [
            {"account": name, **{key: row[key] for key in ("user_id", "username", "display_name")}}
            for name, row in sorted(self._read()["accounts"].items())
        ]

    def get(self, name):
        name = account_name(name)
        row = self._read()["accounts"].get(name)
        if row is None:
            raise AccountError(f"Saved account '{name}' does not exist; use list_accounts")
        return {"account": name, **{key: row[key] for key in ("user_id", "username", "display_name")}}

    def token(self, name):
        name = account_name(name)
        self.get(name)
        try:
            row = self._read()["accounts"][name]
            return self._unprotect(base64.b64decode(row["credential"], validate=True)).decode("ascii")
        except Exception:
            raise AccountError("Cannot decrypt this account for the current Windows user") from None

    def save(self, name, token, identity, *, replace=False, select=False):
        name = account_name(name)
        token = validate_token(token)
        data = self._read()
        if name in data["accounts"] and not replace:
            raise AccountError(f"Account '{name}' already exists; use replace=true to update it")
        try:
            encrypted = self._protect(token.encode("ascii"))
        except AccountError:
            raise
        except Exception:
            raise AccountError("Cannot encrypt the account with Windows DPAPI") from None
        data["accounts"][name] = {
            "user_id": str(identity["user_id"]),
            "username": identity["username"],
            "display_name": identity["display_name"],
            "credential": base64.b64encode(encrypted).decode("ascii"),
        }
        if select:
            data["active_account"] = name
        self._write(data)
        return self.get(name)

    def select(self, name):
        name = account_name(name)
        data = self._read()
        if name not in data["accounts"]:
            raise AccountError(f"Saved account '{name}' does not exist; use list_accounts")
        data["active_account"] = name
        self._write(data)
