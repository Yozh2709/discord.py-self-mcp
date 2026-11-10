"""Account transitions and a shared client reference for every Discord tool."""

import asyncio
from contextlib import asynccontextmanager, suppress
import os

import discord

from .account_store import AccountError, AccountStore, account_name, validate_token
from . import modal_store
from .logging_utils import log_to_stderr


class ClientProxy:
    """Imports keep this reference while its underlying Discord client changes."""

    def __init__(self, client):
        self._target = client

    def __getattr__(self, name):
        return getattr(self._target, name)


class SessionGate:
    """Concurrent commands share a session; a switch waits for all of them."""

    def __init__(self, switch_timeout=60):
        self._condition = asyncio.Condition()
        self._readers = 0
        self._switching = False
        self._waiting = 0
        self._switch_timeout = switch_timeout

    @asynccontextmanager
    async def operation(self):
        async with self._condition:
            await self._condition.wait_for(lambda: not self._switching and not self._waiting)
            self._readers += 1
        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                self._condition.notify_all()

    @asynccontextmanager
    async def exclusive(self):
        async with self._condition:
            self._waiting += 1
            try:
                try:
                    await asyncio.wait_for(
                        self._condition.wait_for(lambda: not self._switching and not self._readers),
                        timeout=self._switch_timeout,
                    )
                except asyncio.TimeoutError:
                    raise AccountError("Commands are still running; retry switch_account after they finish") from None
                self._switching = True
            finally:
                self._waiting -= 1
                self._condition.notify_all()
        try:
            yield
        finally:
            async with self._condition:
                self._switching = False
                self._condition.notify_all()


def identity(client):
    user = client.user
    return {
        "user_id": str(user.id),
        "username": user.name,
        "display_name": getattr(user, "global_name", None) or user.name,
    }


class AccountManager:
    def __init__(self, client, factory, *, store=None, connect_timeout=60):
        self.client = client
        self.factory = factory
        self.store = store or AccountStore()
        self.gate = SessionGate()
        self.connect_timeout = connect_timeout
        self.active_account = None
        self.last_error = None
        self._connection_task = None
        self._startup_task = None

    def list_accounts(self):
        return {
            "active_account": self.active_account,
            "startup_account": self.store.selected(),
            "ready": self.client.is_ready(),
            "connection_error": self.last_error,
            "accounts": [
                {**row, "active": row["account"] == self.active_account}
                for row in self.store.list_accounts()
            ],
        }

    async def _stop(self, client, task=None):
        try:
            await asyncio.wait_for(client.close(), timeout=10)
        except Exception:
            log_to_stderr("[ACCOUNTS] Connection cleanup incomplete")
        finally:
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _login(self, client, token):
        try:
            await asyncio.wait_for(client.login(token), timeout=30)
        except discord.LoginFailure:
            raise AccountError("Discord rejected this token") from None
        except asyncio.TimeoutError:
            raise AccountError("Discord login timed out") from None
        except Exception:
            raise AccountError("Discord login failed; check the connection or account access") from None

    async def save_account(self, name, token, *, replace=False):
        name = account_name(name)
        token = validate_token(token)
        if not isinstance(replace, bool):
            raise AccountError("replace must be true or false")
        if any(row["account"] == name for row in self.store.list_accounts()) and not replace:
            raise AccountError(f"Account '{name}' already exists; use replace=true to update it")
        probe = self.factory()
        try:
            await self._login(probe, token)
            details = identity(probe)
            if name == self.active_account and details["user_id"] != str(self.client.user.id):
                raise AccountError("Use a different profile name for a different Discord user")
            return {
                "saved": True,
                **self.store.save(name, token, details, replace=replace),
                "active_account": self.active_account,
            }
        finally:
            await self._stop(probe)

    async def _prepare(self, token, expected_id=None):
        candidate = self.factory()
        task = None
        ready = None
        try:
            await self._login(candidate, token)
            if expected_id is not None and str(candidate.user.id) != expected_id:
                raise AccountError("Saved token belongs to a different user; save that account again")
            task = asyncio.create_task(candidate.connect())
            ready = asyncio.create_task(candidate.wait_until_ready())
            done, _ = await asyncio.wait({task, ready}, timeout=self.connect_timeout, return_when=asyncio.FIRST_COMPLETED)
            if ready not in done or task.done() or not candidate.is_ready():
                raise AccountError("Discord did not become ready; the previous account is still selected")
            return candidate, task
        except BaseException:
            await self._stop(candidate, task)
            raise
        finally:
            if ready:
                ready.cancel()
                await asyncio.gather(ready, return_exceptions=True)

    async def switch_account(self, name):
        name = account_name(name)
        async with self.gate.exclusive():
            details = self.store.get(name)
            token = self.store.token(name)
            if name == self.active_account and self.client.is_ready() and token == os.getenv("DISCORD_TOKEN"):
                return {"switched": False, "ready": True, **details}
            try:
                candidate, task = await self._prepare(token, details["user_id"])
            except (AccountError, asyncio.CancelledError):
                raise
            except Exception:
                raise AccountError("Discord connection failed; the previous account is still selected") from None
            try:
                self.store.select(name)
            except BaseException:
                await self._stop(candidate, task)
                raise
            previous, previous_task = self.client._target, self._connection_task
            self.client._target = candidate
            self._connection_task = task
            self.active_account = name
            self.last_error = None
            os.environ["DISCORD_TOKEN"] = token
            modal_store.clear()
            task.add_done_callback(self._connection_finished)
            await self._stop(previous, previous_task)
            return {"switched": True, "ready": True, **details}

    def _connection_finished(self, task):
        if task.cancelled():
            return
        error = task.exception()
        if task is self._connection_task and error is not None:
            self.last_error = "Discord connection ended; reconnect or switch to a saved account"
            log_to_stderr("[ACCOUNTS] " + self.last_error)

    async def start_initial(self, fallback_token=None):
        selected = os.getenv("DISCORD_ACCOUNT") or self.store.selected()
        if selected:
            self._startup_task = asyncio.create_task(self._initial_saved(selected))
        elif fallback_token:
            self._startup_task = asyncio.create_task(self._initial_token(validate_token(fallback_token)))
        else:
            raise AccountError("DISCORD_TOKEN is not set and no saved account is selected")

    async def _initial_saved(self, name):
        try:
            await self.switch_account(name)
        except Exception as exc:
            self.last_error = str(exc) if isinstance(exc, AccountError) else "Saved account could not connect"
            log_to_stderr("[ACCOUNTS] " + self.last_error)

    async def _initial_token(self, token):
        async with self.gate.exclusive():
            candidate = task = None
            try:
                candidate, task = await self._prepare(token)
                rows = self.store.list_accounts()
                name = next((row["account"] for row in rows if row["user_id"] == str(candidate.user.id)), None)
                if name is None:
                    name = "main"
                    if any(row["account"] == name for row in rows):
                        name = f"user-{candidate.user.id}"
                    self.store.save(name, token, identity(candidate), select=True)
                else:
                    self.store.save(name, token, identity(candidate), replace=True, select=True)
                self.client._target = candidate
                self._connection_task = task
                self.active_account = name
                os.environ["DISCORD_TOKEN"] = token
                task.add_done_callback(self._connection_finished)
            except Exception as exc:
                if candidate:
                    await self._stop(candidate, task)
                self.last_error = str(exc) if isinstance(exc, AccountError) else "Initial account connection failed"
                log_to_stderr("[ACCOUNTS] " + self.last_error)

    async def shutdown(self):
        if self._startup_task and not self._startup_task.done():
            self._startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._startup_task
        await self._stop(self.client._target, self._connection_task)
