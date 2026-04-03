"""Tests for settings/session lifecycle logic in chainlit_app.py."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from apps.chat.server.config import ChatSettings

CHAINLIT_APP = Path(__file__).resolve().parents[3] / "apps" / "chat" / "chainlit_app.py"


def _extract_callable_source(name: str) -> str:
    """Extract a top-level def/async def body from chainlit_app.py."""
    source = CHAINLIT_APP.read_text()
    markers = [f"def {name}(", f"async def {name}("]
    start = min(source.index(marker) for marker in markers if marker in source)
    lines = source[start:].split("\n")
    func_lines: list[str] = []
    for i, line in enumerate(lines):
        if (
            i > 0
            and line
            and not line[0].isspace()
            and line.startswith(("def ", "async def ", "class ", "@"))
        ):
            break
        func_lines.append(line)
    return "\n".join(func_lines)


def _load_helpers(*names: str) -> dict[str, object]:
    """Exec selected helpers from chainlit_app.py into a namespace."""
    import re as _re

    ns: dict[str, object] = {
        "ChatSettings": ChatSettings,
        "SecretStr": SecretStr,
        # session ID sanitization used by on_chat_start / on_settings_update
        "_SESSION_ID_RE": _re.compile(r"[^a-zA-Z0-9_-]"),
        "_sanitize_session_id": lambda raw: _re.sub(r"[^a-zA-Z0-9_-]", "", raw)[:128] or "default",
    }
    for name in names:
        exec(_extract_callable_source(name), ns)  # noqa: S102
    return ns


class FakeUserSession:
    """Minimal Chainlit user_session stand-in."""

    def __init__(self, initial: dict[str, object] | None = None) -> None:
        self._data = dict(initial or {})

    def get(self, key: str, default: object | None = None) -> object | None:
        return self._data.get(key, default)

    def set(self, key: str, value: object) -> None:
        self._data[key] = value


class FakeMessage:
    """Collect sent Chainlit message content."""

    def __init__(self, content: str, sink: list[str]) -> None:
        self._content = content
        self._sink = sink

    async def send(self) -> FakeMessage:
        self._sink.append(self._content)
        return self


class FakeChainlit:
    """Tiny Chainlit stub for lifecycle tests."""

    def __init__(self, user_session: FakeUserSession, messages: list[str]) -> None:
        self.user_session = user_session
        self._messages = messages

    def Message(self, *, content: str = "", elements=None) -> FakeMessage:  # noqa: ANN001, N802
        return FakeMessage(content, self._messages)


class TestBuildUpdatedSettings:
    """Test the settings snapshot builder used during rebuilds."""

    @pytest.fixture(autouse=True)
    def _load_helper(self) -> None:
        self.build = _load_helpers("_build_updated_settings")["_build_updated_settings"]

    def test_wraps_ui_api_key_as_secret_str(self) -> None:
        current = ChatSettings(provider="openai", model="gpt-4o", temperature=0.1)
        updated = self.build(
            current,
            {"api_key": "sk-test-123", "model": "claude-sonnet-4-20250514", "temperature": 0.3},
        )

        assert isinstance(updated.api_key, SecretStr)
        assert updated.api_key.get_secret_value() == "sk-test-123"
        assert updated.model == "claude-sonnet-4-20250514"
        assert updated.temperature == 0.3
        assert updated.provider == "openai"

    def test_keeps_existing_secret_when_ui_key_is_blank(self) -> None:
        current = ChatSettings(api_key="sk-old-secret")
        updated = self.build(current, {"api_key": ""})

        assert isinstance(updated.api_key, SecretStr)
        assert updated.api_key.get_secret_value() == "sk-old-secret"

    def test_validation_is_transactional(self) -> None:
        current = ChatSettings()

        with pytest.raises(Exception):  # noqa: B017, PT011
            self.build(current, {"provider": "not-a-provider"})


class TestCleanupSessionState:
    """Test that chat-end cleanup only targets the active session subtree."""

    @pytest.fixture(autouse=True)
    def _load_helper(self) -> None:
        from loguru import logger

        ns: dict[str, object] = {"Path": Path, "logger": logger}
        exec(_extract_callable_source("_cleanup_session_state"), ns)  # noqa: S102
        self.cleanup = ns["_cleanup_session_state"]

    def test_removes_only_current_session_directory(self, tmp_path: Path) -> None:
        session_root = tmp_path / ".nbadb" / "session"
        active_session = session_root / "active-session"
        other_session = session_root / "other-session"
        active_session.mkdir(parents=True)
        other_session.mkdir(parents=True)

        self.cleanup(session_id="active-session", session_root=session_root)

        assert not active_session.exists()
        assert other_session.exists()
        assert session_root.exists()


@pytest.mark.asyncio
async def test_public_demo_chat_start_shows_settings_and_skips_initial_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Public demo mode opens in a configure-first state with no shared key."""
    config_dir = tmp_path / ".nbadb"
    config_dir.mkdir(parents=True)
    (config_dir / "chat.json").write_text(
        json.dumps({"provider": "openai", "model": "gpt-4.1", "api_key": "sk-owner"})
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NBADB_CHAT_PUBLIC_MODE", "1")

    ns = _load_helpers("_prepare_session_settings", "_settings_can_create_agent", "on_chat_start")
    session = FakeUserSession({"id": "session-1", "chat_profile": "Quick Stats"})
    messages: list[str] = []
    panel_settings: list[ChatSettings] = []
    create_calls: list[tuple[ChatSettings, str | None, str]] = []

    async def fake_send_settings_panel(settings: ChatSettings) -> None:
        panel_settings.append(settings)

    async def fake_create_nba_agent(
        settings: ChatSettings,
        profile: str | None = None,
        session_id: str = "default",
    ) -> object:
        create_calls.append((settings, profile, session_id))
        return object()

    public_msg = "BYO key required"
    ns.update(
        {
            "ChatSettings": lambda: ChatSettings(_json_file=config_dir / "chat.json"),
            "cl": FakeChainlit(session, messages),
            "_send_settings_panel": fake_send_settings_panel,
            "create_nba_agent": fake_create_nba_agent,
            "setup_tracing": lambda settings: ["trace"],
            "_KEY_REQUIRED_PROVIDERS": frozenset(
                {"openai", "anthropic", "google", "custom", "copilot"}
            ),
            "_PUBLIC_DEMO_SETUP_MESSAGE": public_msg,
        }
    )

    await ns["on_chat_start"]()

    settings = session.get("settings")
    assert isinstance(settings, ChatSettings)
    assert settings.public_demo_mode is True
    assert settings.api_key is None
    assert settings.temperature == 0.05
    assert panel_settings and panel_settings[0].public_demo_mode is True
    assert session.get("agent") is None
    assert session.get("callbacks") == []
    assert create_calls == []
    assert messages == [public_msg]


@pytest.mark.asyncio
async def test_public_demo_first_valid_settings_update_creates_agent_and_keeps_key_session_local(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The first valid public-demo settings update lazily creates the agent."""
    config_dir = tmp_path / ".nbadb"
    config_dir.mkdir(parents=True)
    chat_config = config_dir / "chat.json"
    chat_config.write_text(json.dumps({"provider": "openai", "model": "gpt-4.1"}))
    monkeypatch.setenv("HOME", str(tmp_path))

    ns = _load_helpers(
        "_build_updated_settings",
        "_settings_can_create_agent",
        "on_settings_update",
    )
    session = FakeUserSession(
        {
            "settings": ChatSettings(provider="openai", model="gpt-4.1", public_demo_mode=True),
            "session_id": "session-2",
            "chat_profile_name": "Deep Analysis",
            "agent": None,
        }
    )
    messages: list[str] = []
    created: list[tuple[ChatSettings, str | None, str]] = []
    new_agent = object()

    async def fake_create_nba_agent(
        settings: ChatSettings,
        profile: str | None = None,
        session_id: str = "default",
    ) -> object:
        created.append((settings, profile, session_id))
        return new_agent

    ns.update(
        {
            "cl": FakeChainlit(session, messages),
            "create_nba_agent": fake_create_nba_agent,
            "setup_tracing": lambda settings: ["trace"],
            "logger": SimpleNamespace(exception=lambda *args, **kwargs: None),
            "_KEY_REQUIRED_PROVIDERS": frozenset(
                {"openai", "anthropic", "google", "custom", "copilot"}
            ),
            "_PUBLIC_DEMO_SETUP_MESSAGE": "BYO key required",
        }
    )

    await ns["on_settings_update"](
        {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-user-session"}
    )

    stored = session.get("settings")
    assert session.get("agent") is new_agent
    assert session.get("callbacks") == ["trace"]
    assert isinstance(stored, ChatSettings)
    assert isinstance(stored.api_key, SecretStr)
    assert stored.api_key.get_secret_value() == "sk-user-session"
    assert created[0][1] == "Deep Analysis"
    assert created[0][2] == "session-2"
    assert created[0][0].api_key.get_secret_value() == "sk-user-session"
    assert json.loads(chat_config.read_text()) == {"provider": "openai", "model": "gpt-4.1"}
    assert messages == ["Settings updated. Agent reconfigured."]


@pytest.mark.asyncio
async def test_failed_settings_update_keeps_existing_agent_alive() -> None:
    """A rebuild failure leaves the current public-demo session agent intact."""
    ns = _load_helpers(
        "_build_updated_settings",
        "_settings_can_create_agent",
        "on_settings_update",
    )
    old_agent = SimpleNamespace(cleanup=AsyncMock())
    current = ChatSettings(
        provider="openai",
        model="gpt-4.1",
        api_key="sk-old",
        public_demo_mode=True,
    )
    session = FakeUserSession(
        {
            "settings": current,
            "session_id": "session-3",
            "chat_profile_name": "Visualization",
            "agent": old_agent,
        }
    )
    messages: list[str] = []

    async def failing_create_nba_agent(
        settings: ChatSettings,
        profile: str | None = None,
        session_id: str = "default",
    ) -> object:
        raise RuntimeError("boom")

    ns.update(
        {
            "cl": FakeChainlit(session, messages),
            "create_nba_agent": failing_create_nba_agent,
            "setup_tracing": lambda settings: ["trace"],
            "logger": SimpleNamespace(exception=lambda *args, **kwargs: None),
            "_KEY_REQUIRED_PROVIDERS": frozenset(
                {"openai", "anthropic", "google", "custom", "copilot"}
            ),
            "_PUBLIC_DEMO_SETUP_MESSAGE": "BYO key required",
        }
    )

    await ns["on_settings_update"]({"model": "gpt-4.1-mini", "api_key": "sk-new"})

    assert session.get("agent") is old_agent
    old_agent.cleanup.assert_not_awaited()
    assert "Failed to update settings" in messages[0]
    assert "previous agent is still available" in messages[0]
