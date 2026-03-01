from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import polars as pl
import pytest

from nbadb.extract.base import BaseExtractor


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


class TestProxyInjection:
    def test_proxy_url_injected_into_kwargs(self) -> None:
        ext = _StubExtractor()
        ext._proxy_url = "http://proxy:8080"

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"COL": [1]})
        ]
        ext._from_nba_api(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert call_kwargs["proxy"] == "http://proxy:8080"
        assert call_kwargs["timeout"] == 60

    def test_no_proxy_when_none(self) -> None:
        ext = _StubExtractor()
        assert ext._proxy_url is None

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"COL": [1]})
        ]
        ext._from_nba_api(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert "proxy" not in call_kwargs

    def test_explicit_proxy_not_overridden(self) -> None:
        ext = _StubExtractor()
        ext._proxy_url = "http://proxy:8080"

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"COL": [1]})
        ]
        ext._from_nba_api(mock_endpoint, proxy="http://other:9090")
        call_kwargs = mock_endpoint.call_args[1]
        assert call_kwargs["proxy"] == "http://other:9090"

    def test_proxy_injected_in_multi(self) -> None:
        ext = _StubExtractor()
        ext._proxy_url = "http://proxy:8080"

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"COL": [1]})
        ]
        ext._from_nba_api_multi(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert call_kwargs["proxy"] == "http://proxy:8080"


class TestExtractIsAbstract:
    def test_cannot_instantiate_base(self) -> None:
        with pytest.raises(TypeError):
            BaseExtractor()  # type: ignore[abstract]
