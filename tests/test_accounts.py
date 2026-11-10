import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import discord
import pytest

from discord_py_self_mcp import bot, modal_store
from discord_py_self_mcp.account_manager import AccountManager, ClientProxy, SessionGate, identity
from discord_py_self_mcp.account_store import AccountError, AccountStore, account_name
from discord_py_self_mcp.tools import accounts
from discord_py_self_mcp.tools.registry import ToolRegistry, registry


TOKENS = {"token-main": 1, "token-alt": 2, "token-main-new": 1}


class FakeClient:
    def __init__(self, user_id=None, *, login_error=None, connect_error=None, stalled=False):
        self.user = SimpleNamespace(id=user_id, name=f"user{user_id}", global_name=None)
        self.login_error = login_error
        self.connect_error = connect_error
        self.stalled = stalled
        self.ready = asyncio.Event()
        self.login_started = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.closed = False
        self.cached_messages = [user_id]
        self.http = object()
        if user_id:
            self.ready.set()

    async def login(self, token):
        self.login_started.set()
        if self.login_error:
            raise self.login_error
        user_id = TOKENS[token]
        self.user = SimpleNamespace(id=user_id, name=f"user{user_id}", global_name=f"Display{user_id}")
        self.cached_messages = [user_id]

    async def connect(self):
        if self.connect_error:
            raise self.connect_error
        if not self.stalled:
            self.ready.set()
        await self.disconnected.wait()

    async def wait_until_ready(self):
        await self.ready.wait()

    def is_ready(self):
        return self.ready.is_set() and not self.closed

    async def close(self):
        self.closed = True
        self.ready.clear()
        self.disconnected.set()


@pytest.fixture
def store(tmp_path):
    return AccountStore(
        tmp_path / "accounts.json",
        protect=lambda value: b"encrypted:" + value[::-1],
        unprotect=lambda value: value[len(b"encrypted:"):][::-1],
    )


@pytest.fixture
def manager(store, monkeypatch):
    store.save("main", "token-main", identity(FakeClient(1)), select=True)
    store.save("alt", "token-alt", identity(FakeClient(2)))
    old = FakeClient(1)
    instance = AccountManager(ClientProxy(old), FakeClient, store=store, connect_timeout=0.05)
    instance.active_account = "main"
    monkeypatch.setenv("DISCORD_TOKEN", "token-main")
    monkeypatch.delenv("DISCORD_ACCOUNT", raising=False)
    yield instance
    modal_store.clear()


def test_store_round_trip_redacts_and_remembers_selection(store):
    store.save("Main", "token-main", {"user_id": "1", "username": "one", "display_name": "One"}, select=True)
    reloaded = AccountStore(store.path, protect=store._protect, unprotect=store._unprotect)
    assert reloaded.token("MAIN") == "token-main"
    assert reloaded.selected() == "main"
    assert "token-main" not in store.path.read_text(encoding="utf-8")
    assert "credential" not in json.dumps(reloaded.list_accounts())
    assert "token-main" not in json.dumps(reloaded.get("main"))


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_real_dpapi_round_trip_without_plaintext(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    store.save("main", "fake-private-credential", {"user_id": "1", "username": "one", "display_name": "One"})
    assert store.token("main") == "fake-private-credential"
    assert "fake-private-credential" not in store.path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["../secret", "", "with space", "a" * 49, None])
def test_profile_name_validation(name):
    with pytest.raises(AccountError):
        account_name(name)


def test_existing_profile_requires_explicit_replacement(store):
    details = {"user_id": "1", "username": "one", "display_name": "One"}
    store.save("main", "token-main", details)
    with pytest.raises(AccountError, match="replace=true"):
        store.save("main", "token-main-new", details)
    assert store.token("main") == "token-main"
    store.save("main", "token-main-new", details, replace=True)
    assert store.token("main") == "token-main-new"


def test_corrupt_store_is_not_overwritten(store):
    store.path.write_text("broken-file", encoding="utf-8")
    with pytest.raises(AccountError, match="Cannot read"):
        store.save("main", "token-main", {"user_id": "1", "username": "one", "display_name": "One"})
    assert store.path.read_text(encoding="utf-8") == "broken-file"


def test_crypto_errors_do_not_echo_credentials(store, monkeypatch):
    store.save("main", "token-main", {"user_id": "1", "username": "one", "display_name": "One"})
    def fail(value):
        raise RuntimeError("secret-token-in-library-error")
    monkeypatch.setattr(store, "_unprotect", fail)
    with pytest.raises(AccountError) as exc:
        store.token("main")
    assert "secret-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_switch_moves_all_imported_client_references_and_discards_old_cache(manager):
    proxy = manager.client
    old = proxy._target
    old_http = proxy.http
    modal_store.put(SimpleNamespace(custom_id="old-modal"))
    result = await manager.switch_account("ALT")
    assert result == {"switched": True, "ready": True, "account": "alt", "user_id": "2", "username": "user2", "display_name": "user2"}
    assert manager.client is proxy
    assert proxy.user.id == 2 and proxy.cached_messages == [2]
    assert proxy.http is not old_http
    assert old.closed
    assert modal_store.known_ids() == []
    assert manager.store.selected() == "alt"
    assert os.environ["DISCORD_TOKEN"] == "token-alt"
    assert manager.list_accounts()["active_account"] == "alt"
    assert "token-alt" not in json.dumps(result)
    await manager.shutdown()


@pytest.mark.parametrize("failure", ["login", "gateway", "timeout", "identity", "persist"])
@pytest.mark.asyncio
async def test_failed_switch_preserves_current_account_and_cleans_candidate(manager, monkeypatch, failure):
    old = manager.client._target
    candidate = FakeClient(
        login_error=discord.LoginFailure("private-credential") if failure == "login" else None,
        connect_error=RuntimeError("private-credential") if failure == "gateway" else None,
        stalled=failure == "timeout",
    )
    manager.factory = lambda: candidate
    if failure == "identity":
        details = manager.store.get("alt")
        manager.store.save("alt", "token-main", details, replace=True)
    if failure == "persist":
        def fail(name):
            raise AccountError("Cannot persist selection")
        monkeypatch.setattr(manager.store, "select", fail)
    with pytest.raises(AccountError) as exc:
        await manager.switch_account("alt")
    assert "private-credential" not in str(exc.value)
    assert manager.client._target is old
    assert old.is_ready() and not old.closed
    assert manager.active_account == "main"
    assert manager.store.selected() == "main"
    assert os.environ["DISCORD_TOKEN"] == "token-main"
    assert candidate.closed


@pytest.mark.asyncio
async def test_switch_to_ready_current_profile_is_idempotent(manager):
    manager.factory = Mock(side_effect=AssertionError("unnecessary reconnect"))
    assert not (await manager.switch_account("main"))["switched"]
    manager.factory.assert_not_called()


@pytest.mark.asyncio
async def test_saved_active_token_update_takes_effect_on_switch(manager):
    old = manager.client._target
    await manager.save_account("main", "token-main-new", replace=True)
    assert manager.client._target is old
    assert os.environ["DISCORD_TOKEN"] == "token-main"
    assert (await manager.switch_account("main"))["switched"]
    assert old.closed and manager.client.user.id == 1
    assert os.environ["DISCORD_TOKEN"] == "token-main-new"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_late_error_from_previous_connection_does_not_mark_new_account_failed(manager):
    previous = asyncio.get_running_loop().create_future()
    previous.set_exception(RuntimeError("old connection failed"))
    await manager.switch_account("alt")
    manager._connection_finished(previous)
    assert manager.last_error is None and manager.client.is_ready()
    await manager.shutdown()


@pytest.mark.asyncio
async def test_save_validates_without_switching_and_closes_probe(manager):
    candidate = FakeClient()
    manager.factory = lambda: candidate
    result = await manager.save_account("work", "token-alt")
    assert result["user_id"] == "2" and result["active_account"] == "main"
    assert manager.store.token("work") == "token-alt"
    assert candidate.closed and not candidate.ready.is_set()
    assert manager.client.user.id == 1
    assert "token-alt" not in json.dumps(result)


@pytest.mark.asyncio
async def test_active_profile_cannot_silently_change_identity(manager):
    with pytest.raises(AccountError, match="different profile"):
        await manager.save_account("main", "token-alt", replace=True)
    assert manager.store.token("main") == "token-main"


@pytest.mark.asyncio
async def test_unknown_profile_does_not_disconnect(manager):
    with pytest.raises(AccountError, match="does not exist"):
        await manager.switch_account("missing")
    assert manager.client.is_ready()


@pytest.mark.asyncio
async def test_switch_cancellation_preserves_session_and_releases_gate(manager):
    candidate = FakeClient(stalled=True)
    manager.factory = lambda: candidate
    transition = asyncio.create_task(manager.switch_account("alt"))
    await candidate.login_started.wait()
    transition.cancel()
    with pytest.raises(asyncio.CancelledError):
        await transition
    assert candidate.closed and manager.client.user.id == 1
    async with manager.gate.operation():
        assert manager.client.is_ready()


@pytest.mark.asyncio
async def test_registry_switch_waits_for_inflight_command_and_holds_new_commands(manager, monkeypatch):
    monkeypatch.setattr(bot, "account_manager", manager)
    custom = ToolRegistry()
    started = asyncio.Event()
    release = asyncio.Event()
    seen = []
    async def old_command(arguments):
        started.set()
        await release.wait()
        seen.append(("old", manager.client.user.id))
        return []
    async def next_command(arguments):
        seen.append(("new", manager.client.user.id))
        return []
    async def switch(arguments):
        return await manager.switch_account("alt")
    custom.register("send", "test", {})(old_command)
    custom.register("read", "test", {})(next_command)
    custom.register("switch_account", "test", {})(switch)
    first = asyncio.create_task(custom.call_tool("send", {}))
    await started.wait()
    change = asyncio.create_task(custom.call_tool("switch_account", {}))
    await asyncio.sleep(0)
    following = asyncio.create_task(custom.call_tool("read", {}))
    await asyncio.sleep(0)
    assert not change.done() and not following.done()
    assert manager.client.user.id == 1
    release.set()
    await asyncio.wait_for(asyncio.gather(first, change, following), timeout=1)
    assert seen == [("old", 1), ("new", 2)]
    await manager.shutdown()


@pytest.mark.asyncio
async def test_regular_commands_can_still_run_concurrently(manager):
    entered = asyncio.Event()
    release = asyncio.Event()
    async def first():
        async with manager.gate.operation():
            entered.set()
            await release.wait()
    pending = asyncio.create_task(first())
    await entered.wait()
    async with manager.gate.operation():
        release.set()
    await pending


@pytest.mark.asyncio
async def test_switch_wait_is_bounded_and_does_not_leave_commands_blocked():
    gate = SessionGate(switch_timeout=0.001)
    async with gate.operation():
        with pytest.raises(AccountError, match="Commands are still running"):
            async with gate.exclusive():
                pytest.fail("switch should not enter")
    async with gate.operation():
        assert gate._readers == 1


@pytest.mark.asyncio
async def test_initial_login_migrates_token_to_main_and_reuses_saved_selection(store, monkeypatch):
    monkeypatch.delenv("DISCORD_ACCOUNT", raising=False)
    first = AccountManager(ClientProxy(FakeClient()), FakeClient, store=store, connect_timeout=0.05)
    await first.start_initial("token-main")
    await first._startup_task
    assert first.active_account == "main" and store.token("main") == "token-main"
    await first.save_account("alt", "token-alt")
    await first.switch_account("alt")
    await first.shutdown()
    second = AccountManager(ClientProxy(FakeClient()), FakeClient, store=store, connect_timeout=0.05)
    await second.start_initial("token-main")
    await second._startup_task
    assert second.active_account == "alt" and second.client.user.id == 2
    await second.shutdown()


@pytest.mark.asyncio
async def test_initial_bad_token_produces_safe_status_instead_of_unhandled_task(store, monkeypatch):
    monkeypatch.delenv("DISCORD_ACCOUNT", raising=False)
    candidate = FakeClient(login_error=discord.LoginFailure("private-credential"))
    instance = AccountManager(ClientProxy(FakeClient()), lambda: candidate, store=store)
    await instance.start_initial("token-main")
    await instance._startup_task
    status = instance.list_accounts()
    assert not status["ready"] and status["active_account"] is None
    assert status["connection_error"] == "Discord rejected this token"
    assert candidate.closed and store.list_accounts() == []


@pytest.mark.asyncio
async def test_account_tool_schema_and_results_exclude_tokens(manager, monkeypatch):
    monkeypatch.setattr(accounts, "account_manager", manager)
    status = json.loads((await accounts.list_accounts({}))[0].text)
    assert status["active_account"] == "main"
    saved = json.loads((await accounts.save_account({"account": "work", "token": "token-alt"}))[0].text)
    assert saved["saved"] and "token-alt" not in json.dumps(saved)
    assert {"account", "token"} <= set(registry.tools["save_account"].inputSchema["required"])
    assert registry.tools["switch_account"].inputSchema["required"] == ["account"]
