from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import polars as pl
import pytest

from nbadb.core.errors import ValidationError as NbaDbValidationError
from nbadb.extract.base import BaseExtractor
from nbadb.extract.raw_schema_registry import get_raw_schema


class _StubExtractor(BaseExtractor):
    endpoint_name = "stub"
    category = "test"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return pl.DataFrame({"a": [1, 2]})


class TestFromNbaApi:
    def test_lowercase_columns(self) -> None:
        ext = _StubExtractor()
        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"PLAYER_ID": [1], "PTS": [25]})
        ]
        result = ext._from_nba_api(mock_endpoint)
        assert set(result.columns) == {"player_id", "pts"}
        assert result.shape == (1, 2)

    def test_preserves_nba_stat_shorthand_columns(self) -> None:
        ext = _StubExtractor()
        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"FG3M": [4], "FG2A": [7], "PCT_AST_2PM": [0.6]})
        ]
        result = ext._from_nba_api(mock_endpoint)
        assert set(result.columns) == {"fg3m", "fg2a", "pct_ast_2pm"}

    def test_empty_data_frames(self) -> None:
        ext = _StubExtractor()
        mock_endpoint = MagicMock()
        mock_endpoint.return_value.get_data_frames.return_value = []
        result = ext._from_nba_api(mock_endpoint)
        assert result.shape == (0, 0)


class TestFromNbaApiMulti:
    def test_returns_multiple_lowercased(self) -> None:
        ext = _StubExtractor()
        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"GAME_ID": ["001"], "PTS": [100]}),
            pd.DataFrame({"TEAM_ID": [1], "WINS": [50]}),
        ]
        results = ext._from_nba_api_multi(mock_endpoint)
        assert len(results) == 2
        assert "game_id" in results[0].columns
        assert "team_id" in results[1].columns

    def test_skips_unsafe_generic_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = _StubExtractor()
        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"GAME_ID": ["001"]}),
            pd.DataFrame({"TEAM_ID": [1]}),
        ]
        monkeypatch.setattr(
            ext,
            "_validate",
            lambda _df: (_ for _ in ()).throw(AssertionError("should not validate multi packets")),
        )

        results = ext._from_nba_api_multi(mock_endpoint)
        assert len(results) == 2


class TestTimeoutInjection:
    def test_timeout_override_injected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NBADB_REQUEST_TIMEOUT", "15")
        ext = _StubExtractor()

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [pd.DataFrame({"COL": [1]})]
        ext._from_nba_api(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert call_kwargs["timeout"] == 15

    def test_invalid_timeout_override_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NBADB_REQUEST_TIMEOUT", "abc")
        ext = _StubExtractor()

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [pd.DataFrame({"COL": [1]})]
        ext._from_nba_api(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert "timeout" not in call_kwargs

    def test_runner_timeout_override_takes_precedence(self) -> None:
        ext = _StubExtractor()
        ext._request_timeout_override = 45

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [pd.DataFrame({"COL": [1]})]
        ext._from_nba_api(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert call_kwargs["timeout"] == 45

    def test_timeout_cap_lowers_runner_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NBADB_REQUEST_TIMEOUT_CAP", "10")
        ext = _StubExtractor()
        ext._request_timeout_override = 45

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [pd.DataFrame({"COL": [1]})]
        ext._from_nba_api(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert call_kwargs["timeout"] == 10

    def test_invalid_timeout_cap_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NBADB_REQUEST_TIMEOUT_CAP", "abc")
        ext = _StubExtractor()
        ext._request_timeout_override = 45

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [pd.DataFrame({"COL": [1]})]
        ext._from_nba_api(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert call_kwargs["timeout"] == 45


class TestExtractIsAbstract:
    def test_cannot_instantiate_base(self) -> None:
        with pytest.raises(TypeError):
            BaseExtractor()  # type: ignore[abstract]


class TestSafeFromPandas:
    def test_clean_conversion(self) -> None:
        import pandas as pd

        from nbadb.extract.base import _safe_from_pandas

        pdf = pd.DataFrame({"A": [1, 2, 3], "B": ["x", "y", "z"]})
        result = _safe_from_pandas(pdf)
        assert isinstance(result, pl.DataFrame)
        assert result.shape == (3, 2)

    def test_mixed_type_fallback_numeric(self) -> None:
        from unittest.mock import patch as _patch

        import pandas as pd

        from nbadb.extract.base import _safe_from_pandas

        # Force the initial pl.from_pandas to fail, triggering the fallback
        pdf = pd.DataFrame({"A": pd.array([1, 2, 3], dtype=object)})
        orig_from_pandas = pl.from_pandas
        call_count = 0

        def _failing_from_pandas(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TypeError("simulated Arrow failure")
            return orig_from_pandas(*args, **kwargs)

        with _patch("nbadb.extract.base.pl.from_pandas", side_effect=_failing_from_pandas):
            result = _safe_from_pandas(pdf)
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 3

    def test_mixed_type_fallback_str(self) -> None:
        from unittest.mock import patch as _patch

        import pandas as pd

        from nbadb.extract.base import _safe_from_pandas

        # Force Arrow failure, then fallback tries pd.to_numeric which fails on "foo"
        pdf = pd.DataFrame({"A": pd.array(["foo", None, "bar"], dtype=object)})
        orig_from_pandas = pl.from_pandas
        call_count = 0

        def _failing_from_pandas(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TypeError("simulated Arrow failure")
            return orig_from_pandas(*args, **kwargs)

        with _patch("nbadb.extract.base.pl.from_pandas", side_effect=_failing_from_pandas):
            result = _safe_from_pandas(pdf)
        assert isinstance(result, pl.DataFrame)

    def test_nan_to_null(self) -> None:
        import numpy as np
        import pandas as pd

        from nbadb.extract.base import _safe_from_pandas

        pdf = pd.DataFrame({"A": [1.0, np.nan, 3.0]})
        result = _safe_from_pandas(pdf)
        assert result["A"].null_count() == 1


class TestLiveSnapshotContract:
    def test_injects_snapshot_metadata_and_param_backed_keys(self) -> None:
        frame = pl.DataFrame({"action_number": [1]})
        snapshot_at = datetime(2026, 4, 17, 12, 30, tzinfo=UTC)

        result = BaseExtractor._apply_live_snapshot_contract(
            frame,
            source_endpoint="live_play_by_play",
            natural_keys=("game_id", "action_number"),
            snapshot_at=snapshot_at,
            params={"game_id": "001"},
        )

        assert result.columns == [
            "action_number",
            "game_id",
            "snapshot_at",
            "snapshot_date",
            "source_endpoint",
            "payload_json",
        ]
        assert result.to_dicts() == [
            {
                "action_number": 1,
                "game_id": "001",
                "snapshot_at": snapshot_at,
                "snapshot_date": snapshot_at.date(),
                "source_endpoint": "live_play_by_play",
                "payload_json": None,
            }
        ]

    def test_raises_when_non_empty_live_payload_lacks_required_key(self) -> None:
        frame = pl.DataFrame({"value": [1]})

        with pytest.raises(
            NbaDbValidationError,
            match="missing required natural keys: game_id",
        ):
            BaseExtractor._apply_live_snapshot_contract(
                frame,
                source_endpoint="live_score_board",
                natural_keys=("game_id",),
                snapshot_at=datetime(2026, 4, 17, tzinfo=UTC),
                params={},
            )


class TestSchemaValidationTranslation:
    def test_validate_translates_schema_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = _StubExtractor()

        class _BrokenSchema:
            @staticmethod
            def validate(_df: pl.DataFrame) -> pl.DataFrame:
                raise ValueError("bad schema")

        monkeypatch.setattr("nbadb.extract.base.get_raw_schema", lambda _endpoint: _BrokenSchema)

        with pytest.raises(NbaDbValidationError, match="stub: raw schema validation failed"):
            ext._validate(pl.DataFrame({"a": [1]}))

    def test_live_validation_translates_schema_errors(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = _StubExtractor()

        class _BrokenSchema:
            @staticmethod
            def validate(_df: pl.DataFrame) -> pl.DataFrame:
                raise ValueError("bad live schema")

        class _LiveResult:
            games = [{"gameId": "001"}]

        monkeypatch.setattr(
            "nbadb.extract.base.get_raw_schema",
            lambda endpoint: _BrokenSchema if endpoint == "live_score_board" else None,
        )

        with pytest.raises(
            NbaDbValidationError,
            match="live_score_board: raw schema validation failed",
        ):
            ext._from_nba_live(
                lambda **_kwargs: _LiveResult(),
                "games",
                source_endpoint="live_score_board",
                natural_keys=("game_id",),
            )


class TestRawSchemaRegistry:
    def test_get_raw_schema_uses_shared_registry_aliases(self) -> None:
        schedule_schema = get_raw_schema("schedule")
        live_schema = get_raw_schema("live_box_score.home_team_stats")

        assert schedule_schema is not None
        assert schedule_schema.__name__ == "RawScheduleLeagueV2Schema"
        assert live_schema is not None
        assert live_schema.__name__ == "RawLiveBoxScoreTeamStatsSchema"

    def test_get_raw_schema_resolves_misc_leader_endpoints(self) -> None:
        dunk_schema = get_raw_schema("dunk_score_leaders")
        gravity_schema = get_raw_schema("gravity_leaders")

        assert dunk_schema is not None
        assert dunk_schema.__name__ == "RawDunkScoreLeadersSchema"
        assert gravity_schema is not None
        assert gravity_schema.__name__ == "RawGravityLeadersSchema"
