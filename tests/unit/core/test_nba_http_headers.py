from nba_api.stats.library.http import STATS_HEADERS

from nbadb.core import NBA_HEADERS
from nbadb.core.types import NBA_HEADERS as TYPES_NBA_HEADERS


def test_public_nba_headers_match_pinned_runtime_contract() -> None:
    assert tuple(NBA_HEADERS.items()) == tuple(STATS_HEADERS.items())
    assert TYPES_NBA_HEADERS is NBA_HEADERS
    assert NBA_HEADERS is not STATS_HEADERS
