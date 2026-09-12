"""Unit tests for chat/chainlit_app handlers (RV-023)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nbadb.chat.artifacts import ArtifactStore
from nbadb.chat.memory import MemoryStore
from nbadb.chat.runtime.core import ChatRuntime
from nbadb.chat.sql import QueryResponse


def _load_chainlit_app(monkeypatch: pytest.MonkeyPatch):
    """Load chainlit_app with a stub chainlit module."""
    messages: list[Any] = []

    class _Message:
        def __init__(self, content: str = "", elements: list | None = None) -> None:
            self.content = content
            self.elements = elements or []
            self.send = AsyncMock(side_effect=lambda: messages.append(self))

    class _Text:
        def __init__(self, name: str, content: str, display: str = "side") -> None:
            self.name = name
            self.content = content
            self.display = display

    class _UserSession:
        def __init__(self) -> None:
            self._data: dict = {}

        def set(self, key: str, value: object) -> None:
            self._data[key] = value

        def get(self, key: str, default: object = None) -> object:
            return self._data.get(key, default)

    user_session = _UserSession()
    stub = SimpleNamespace(
        Message=_Message,
        Text=_Text,
        user_session=user_session,
        context=SimpleNamespace(session=SimpleNamespace(id="sess-test")),
        on_chat_start=lambda fn: fn,
        on_message=lambda fn: fn,
        Element=object,
        _messages=messages,
    )
    monkeypatch.setitem(sys.modules, "chainlit", stub)

    app_path = Path(__file__).resolve().parents[3] / "chat" / "chainlit_app.py"
    spec = importlib.util.spec_from_file_location("nbadb_chainlit_app_under_test", app_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, stub


@pytest.mark.asyncio
async def test_on_chat_start_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import duckdb

    db = tmp_path / "nba.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("SELECT 1")

    mod, stub = _load_chainlit_app(monkeypatch)
    runtime = ChatRuntime(
        duckdb_path=db,
        memory_store=MemoryStore(root=tmp_path / "memory"),
        artifact_store=ArtifactStore(root=tmp_path / "artifacts"),
    )
    monkeypatch.setattr(mod, "build_runtime", lambda: runtime)

    await mod.on_chat_start()

    assert stub.user_session.get("runtime") is runtime
    assert stub._messages
    assert "catalog" in stub._messages[0].content.lower()


@pytest.mark.asyncio
async def test_on_chat_start_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mod, stub = _load_chainlit_app(monkeypatch)
    monkeypatch.setattr(
        mod,
        "build_runtime",
        lambda: (_ for _ in ()).throw(RuntimeError("missing warehouse")),
    )

    await mod.on_chat_start()

    assert "missing warehouse" in str(stub.user_session.get("runtime_error"))
    assert "Chat startup failed" in stub._messages[0].content


@pytest.mark.asyncio
async def test_on_message_ask_and_save(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import duckdb

    from nbadb.orchestrate.seasons import current_season

    db = tmp_path / "nba.duckdb"
    year = current_season()
    with duckdb.connect(str(db)) as conn:
        conn.execute(
            "CREATE TABLE dim_player (player_id INTEGER, full_name VARCHAR, is_current BOOLEAN)"
        )
        conn.execute(
            "CREATE TABLE agg_player_season ("
            "player_id INTEGER, season_year VARCHAR, season_type VARCHAR, total_pts INTEGER)"
        )
        conn.execute("INSERT INTO dim_player VALUES (1, 'A', TRUE)")
        conn.execute(
            "INSERT INTO agg_player_season VALUES (1, ?, 'Regular Season', 30)",
            [year],
        )

    mod, stub = _load_chainlit_app(monkeypatch)
    runtime = ChatRuntime(
        duckdb_path=db,
        memory_store=MemoryStore(root=tmp_path / "memory"),
        artifact_store=ArtifactStore(root=tmp_path / "artifacts"),
    )
    stub.user_session.set("runtime", runtime)

    message = SimpleNamespace(content="who led scoring?")
    await mod.on_message(message)
    assert stub.user_session.get("last_response") is not None
    answer = stub._messages[-1]
    assert "A" in answer.content
    assert "SELECT" not in answer.content
    assert len(answer.elements) == 1
    assert answer.elements[0].name == "SQL"
    assert "SELECT" in answer.elements[0].content

    save_msg = SimpleNamespace(content="/save Scoring leader")
    await mod.on_message(save_msg)
    assert any("Saved finding" in m.content for m in stub._messages)


@pytest.mark.asyncio
async def test_on_message_keeps_warning_but_renders_sql_only_in_side_element(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = tmp_path / "nba.duckdb"
    db.touch()
    mod, stub = _load_chainlit_app(monkeypatch)
    runtime = ChatRuntime(
        duckdb_path=db,
        memory_store=MemoryStore(root=tmp_path / "memory"),
        artifact_store=ArtifactStore(root=tmp_path / "artifacts"),
    )
    stub.user_session.set("runtime", runtime)
    response = QueryResponse(
        question="show game log",
        route="player_game_log",
        sql="SELECT player_name FROM game_log",
        columns=("player_name",),
        rows=(("LeBron James",),),
        warnings=("Warehouse season lookup was unavailable; used the calendar season.",),
    )
    monkeypatch.setattr(ChatRuntime, "ask", lambda *_args, **_kwargs: response)

    await mod.on_message(SimpleNamespace(content="show game log"))

    answer = stub._messages[-1]
    assert "LeBron James" in answer.content
    assert "Warning: Warehouse season lookup was unavailable" in answer.content
    assert response.sql not in answer.content
    assert [element.content for element in answer.elements] == [response.sql]


@pytest.mark.asyncio
async def test_on_message_bounds_oversized_save_title(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mod, stub = _load_chainlit_app(monkeypatch)
    runtime = ChatRuntime(
        duckdb_path=tmp_path / "nba.duckdb",
        memory_store=MemoryStore(root=tmp_path / "memory"),
        artifact_store=ArtifactStore(root=tmp_path / "artifacts"),
    )
    stub.user_session.set("runtime", runtime)
    stub.user_session.set(
        "last_response",
        QueryResponse(
            question="q",
            route="game_count",
            sql="SELECT 1",
            columns=("count",),
            rows=((1,),),
        ),
    )

    await mod.on_message(SimpleNamespace(content=f"/save {'x' * 201}"))

    assert "Finding was not saved" in stub._messages[-1].content
    assert "200 character limit" in stub._messages[-1].content


@pytest.mark.asyncio
async def test_on_message_runtime_error_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    mod, stub = _load_chainlit_app(monkeypatch)
    stub.user_session.set("runtime_error", "broken")
    await mod.on_message(SimpleNamespace(content="anything"))
    assert "unavailable" in stub._messages[0].content.lower()


@pytest.mark.asyncio
async def test_unsuccessful_question_does_not_replace_last_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import duckdb

    db = tmp_path / "nba.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("SELECT 1")

    mod, stub = _load_chainlit_app(monkeypatch)
    runtime = ChatRuntime(
        duckdb_path=db,
        memory_store=MemoryStore(root=tmp_path / "memory"),
        artifact_store=ArtifactStore(root=tmp_path / "artifacts"),
    )
    prior = object()
    stub.user_session.set("runtime", runtime)
    stub.user_session.set("last_response", prior)

    await mod.on_message(SimpleNamespace(content="unrecognized catalog question xyzzy"))

    assert stub.user_session.get("last_response") is prior


@pytest.mark.asyncio
async def test_on_chat_start_examples_match_catalog_routes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W8.5 R4-F2: welcome examples must route-match real catalog entries."""
    import duckdb

    from nbadb.chat.catalog import default_catalog

    db = tmp_path / "nba.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("SELECT 1")

    mod, stub = _load_chainlit_app(monkeypatch)
    runtime = ChatRuntime(
        duckdb_path=db,
        memory_store=MemoryStore(root=tmp_path / "memory"),
        artifact_store=ArtifactStore(root=tmp_path / "artifacts"),
    )
    monkeypatch.setattr(mod, "build_runtime", lambda: runtime)

    await mod.on_chat_start()

    welcome = stub._messages[0].content
    examples = [line[2:].strip() for line in welcome.splitlines() if line.startswith("- ")]
    assert examples, "welcome message must list example prompts"
    catalog = default_catalog()
    for example in examples:
        assert catalog.match_route(example) is not None, f"example routes nowhere: {example}"
    for dead in ("standings", "pipeline inventory", "how many games", "led scoring"):
        assert dead not in welcome.lower(), f"welcome still shows unmatched example: {dead}"


def test_chainlit_md_examples_match_catalog_routes() -> None:
    """W8.5 R4-F1: documented examples must route-match real catalog entries."""
    from nbadb.chat.catalog import default_catalog

    md_path = Path(__file__).resolve().parents[3] / "chat" / "chainlit.md"
    text = md_path.read_text(encoding="utf-8")
    section = text.split("## Examples", 1)[1].split("##", 1)[0]
    examples = [line[2:].strip() for line in section.splitlines() if line.startswith("- ")]
    assert examples, "chainlit.md must list example prompts"
    catalog = default_catalog()
    for example in examples:
        assert catalog.match_route(example) is not None, f"example routes nowhere: {example}"
