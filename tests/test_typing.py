import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import jsonschema
import pytest

from discord_py_self_mcp import tool_utils
from discord_py_self_mcp.tools import messages, threads
from discord_py_self_mcp.tools.registry import registry
from scripts import daemon, dcli


class RecordingChannel:
    def __init__(self, events, *, typing_error=None, send_error=None):
        self.events = events
        self.typing_error = typing_error
        self.send_error = send_error
        self.active = False
        self.kwargs = None

    @asynccontextmanager
    async def typing(self):
        self.events.append("typing-enter")
        if self.typing_error:
            raise self.typing_error
        self.active = True
        try:
            yield
        finally:
            self.active = False
            self.events.append("typing-exit")

    async def send(self, content, **kwargs):
        assert self.active
        self.events.append(("send", content))
        self.kwargs = kwargs
        if self.send_error:
            raise self.send_error
        return SimpleNamespace(id=999)


@pytest.mark.parametrize("tool,id_key", [("send_message", "channel_id"), ("send_thread_message", "thread_id")])
def test_schema_requires_explicit_typing_duration(tool, id_key):
    schema = registry.tools[tool].inputSchema
    args = {id_key: "1", "content": "hi"}
    assert "typing_seconds" in schema["required"]
    assert "default" not in schema["properties"]["typing_seconds"]
    with pytest.raises(jsonschema.ValidationError, match="typing_seconds"):
        jsonschema.validate(args, schema)
    jsonschema.validate({**args, "typing_seconds": 2.5}, schema)


@pytest.mark.parametrize("value", [None, True, False, "3", 0, -1, 60.1, float("nan"), float("inf"), 10**1000])
def test_invalid_typing_duration(value):
    with pytest.raises(ValueError, match="typing_seconds"):
        tool_utils.validate_typing_seconds(value)


@pytest.mark.parametrize("handler", [messages.send_message, threads.send_thread_message])
@pytest.mark.asyncio
async def test_missing_duration_rejected_before_channel_lookup(monkeypatch, handler):
    client = Mock()
    monkeypatch.setattr(messages, "client", client)
    monkeypatch.setattr(threads, "client", client)
    with pytest.raises(ValueError, match="typing_seconds"):
        await handler({"channel_id": "1", "thread_id": "1", "content": "hi"})
    client.get_channel.assert_not_called()
    client.fetch_channel.assert_not_called()


@pytest.mark.parametrize("mode", ["channel", "thread", "daemon"])
@pytest.mark.asyncio
async def test_typing_happens_after_rate_wait_and_before_send(monkeypatch, mode):
    events = []
    channel = RecordingChannel(events)
    client = SimpleNamespace(get_channel=lambda _: channel)
    monkeypatch.setattr(messages.discord.abc, "Messageable", RecordingChannel)
    monkeypatch.setattr(threads.discord, "Thread", RecordingChannel)
    monkeypatch.setattr(messages, "client", client)
    monkeypatch.setattr(threads, "client", client)

    async def rate_wait(action):
        events.append(("rate", action))

    async def sleep(seconds):
        assert channel.active
        events.append(("sleep", seconds))

    monkeypatch.setattr(messages, "apply_rate_limit", rate_wait)
    monkeypatch.setattr(threads, "apply_rate_limit", rate_wait)
    monkeypatch.setattr(tool_utils.asyncio, "sleep", sleep)

    if mode == "channel":
        result = await messages.send_message({
            "channel_id": "1", "content": "hi", "typing_seconds": 2.5,
            "reply_to_message_id": "456",
        })
        assert channel.kwargs["reference"].message_id == 456
        assert "typing_seconds=2.5" in result[0].text
    elif mode == "thread":
        result = await threads.send_thread_message({
            "thread_id": "1", "content": "hi", "typing_seconds": 2.5,
        })
        assert "typing_seconds=2.5" in result[0].text
    else:
        instance = daemon.DiscordDaemon.__new__(daemon.DiscordDaemon)
        instance.client = client
        result = await instance.handle_command({
            "command": "send_message",
            "args": {"channel_id": 1, "content": "hi", "typing_seconds": 2.5, "reply_to_message_id": 456},
        })
        assert result["success"]
        assert result["typing_seconds"] == 2.5
        assert channel.kwargs["reference"].message_id == 456
    prefix = [] if mode == "daemon" else [("rate", "message")]
    assert events == prefix + ["typing-enter", ("sleep", 2.5), ("send", "hi"), "typing-exit"]
    assert not channel.active


@pytest.mark.parametrize("failure", ["typing", "sleep", "send", "cancel"])
@pytest.mark.asyncio
async def test_failure_cleans_up_typing_and_prevents_early_send(monkeypatch, failure):
    events = []
    channel = RecordingChannel(
        events,
        typing_error=RuntimeError("typing failed") if failure == "typing" else None,
        send_error=RuntimeError("send failed") if failure == "send" else None,
    )

    async def sleep(seconds):
        events.append(("sleep", seconds))
        if failure == "cancel":
            raise asyncio.CancelledError
        if failure == "sleep":
            raise RuntimeError("sleep failed")

    monkeypatch.setattr(tool_utils.asyncio, "sleep", sleep)
    expected = asyncio.CancelledError if failure == "cancel" else RuntimeError
    with pytest.raises(expected):
        await tool_utils.send_with_typing(channel, "hi", 3)
    assert not channel.active
    if failure != "send":
        assert ("send", "hi") not in events
    if failure != "typing":
        assert events[-1] == "typing-exit"


@pytest.mark.asyncio
async def test_daemon_rejects_omitted_duration_before_channel_lookup():
    instance = daemon.DiscordDaemon.__new__(daemon.DiscordDaemon)
    instance.client = Mock()
    result = await instance.handle_command({
        "command": "send_message", "args": {"channel_id": 1, "content": "hi"},
    })
    assert "typing_seconds" in result["error"]
    instance.client.get_channel.assert_not_called()


def test_cli_forwards_required_duration_and_allows_time_for_it(monkeypatch):
    send_request = Mock(return_value={"message_id": 999})
    monkeypatch.setattr(dcli, "send_request", send_request)
    dcli.cmd_send_message(1, "hi", 60, reply_to_message_id=456)
    send_request.assert_called_once_with({
        "command": "send_message",
        "args": {"channel_id": 1, "content": "hi", "typing_seconds": 60.0, "reply_to_message_id": 456},
    }, timeout=90)


def test_cli_parser_requires_duration(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["dcli.py", "send-message", "--channel", "1", "--content", "hi"])
    with pytest.raises(SystemExit) as exc:
        dcli.main()
    assert exc.value.code == 2
    assert "--typing-seconds" in capsys.readouterr().err
