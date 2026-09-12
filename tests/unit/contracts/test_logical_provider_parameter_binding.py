from __future__ import annotations

import json
from dataclasses import replace

import pytest

from nbadb.contracts.logical_provider_parameter_binding import (
    MAX_LOGICAL_PROVIDER_PARAMETER_BINDING_BYTES,
    LogicalProviderParameterBindingError,
    LogicalProviderParameterBindingV1,
    compile_logical_provider_parameter_binding,
    verify_logical_provider_parameter_binding,
)
from nbadb.contracts.raw_request_authority import canonical_semantic_parameters
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_runtime_contracts,
)
from nbadb.extract.bronze import canonical_parameters_sha256
from nbadb.extract.raw_request_capture import (
    RawProviderCallContextV2,
    RawRequestCaptureContextV2,
)

_LOGICAL_PARAMETERS = {
    "season": "2025-26",
    "season_type": "Regular Season",
}
_PROVIDER_PARAMETERS = {
    "season": "2025-26",
    "season_type_all_star": "Regular Season",
}


def _capture_context() -> RawRequestCaptureContextV2:
    endpoint_id = "LeagueGameLog"
    _safe_json, _safe_sha256, provider_request_sha256 = canonical_semantic_parameters(
        "stats",
        endpoint_id,
        _PROVIDER_PARAMETERS,
    )
    provider_call = RawProviderCallContextV2(
        request_ordinal=0,
        semantic_request_sha256="1" * 64,
        logical_invocation_sha256="2" * 64,
        provider_call_role="primary",
        provider_call_ordinal=0,
        source_family="stats",
        endpoint_id=endpoint_id,
        provider_request_sha256=provider_request_sha256,
        endpoint_contract_sha256=endpoint_contract_sha256(pinned_runtime_contracts()[endpoint_id]),
        scope_sha256="3" * 64,
    )
    return RawRequestCaptureContextV2(
        provider_authority_sha256=(staging_route_contract_bundle().provider_authority_sha256),
        source_sha="4" * 40,
        run_id=41,
        run_attempt=2,
        chain_id="chain",
        lane_id="lane",
        provider_calls=(provider_call,),
    )


def _route_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            route.route_id
            for route in staging_route_contract_bundle().routes
            if route.endpoint_name == "league_game_log"
        )
    )


def _binding() -> LogicalProviderParameterBindingV1:
    return compile_logical_provider_parameter_binding(
        raw_request_context=_capture_context(),
        logical_endpoint_name="league_game_log",
        logical_parameters=_LOGICAL_PARAMETERS,
        result_route_ids=_route_ids(),
        provider_semantic_parameters=(_PROVIDER_PARAMETERS,),
    )


def test_compiler_seals_distinct_logical_and_provider_parameter_identities() -> None:
    binding = _binding()
    _safe_json, provider_parameters_sha256, provider_request_sha256 = canonical_semantic_parameters(
        "stats",
        "LeagueGameLog",
        _PROVIDER_PARAMETERS,
    )

    assert binding.logical_parameters_sha256 == canonical_parameters_sha256(_LOGICAL_PARAMETERS)
    assert binding.logical_parameters_sha256 != provider_parameters_sha256
    assert len(binding.provider_entries) == 1
    assert binding.provider_entries[0].safe_parameters_sha256 == (provider_parameters_sha256)
    assert binding.provider_entries[0].provider_request_sha256 == provider_request_sha256
    assert (
        binding.canonical_bytes()
        == json.dumps(
            binding.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    )


def test_external_pin_verification_replays_a_distinct_object() -> None:
    binding = _binding()

    replayed = verify_logical_provider_parameter_binding(
        binding,
        expected_binding_sha256=binding.binding_sha256,
    )

    assert replayed == binding
    assert replayed is not binding
    with pytest.raises(LogicalProviderParameterBindingError, match="external pin"):
        verify_logical_provider_parameter_binding(
            binding,
            expected_binding_sha256="f" * 64,
        )


@pytest.mark.parametrize(
    "encoded",
    (
        b"",
        b"{} ",
        b'{"binding_sha256":"0","binding_sha256":"1"}',
        b"\xff",
    ),
)
def test_canonical_byte_replay_rejects_missing_foreign_or_altered_bytes(
    encoded: bytes,
) -> None:
    with pytest.raises(LogicalProviderParameterBindingError):
        LogicalProviderParameterBindingV1.from_canonical_bytes(encoded)


def test_canonical_byte_replay_is_bounded() -> None:
    with pytest.raises(LogicalProviderParameterBindingError, match="unbounded"):
        LogicalProviderParameterBindingV1.from_canonical_bytes(
            b"{" + b" " * MAX_LOGICAL_PROVIDER_PARAMETER_BINDING_BYTES + b"}"
        )


def test_digest_or_provider_parameter_mutation_fails_closed() -> None:
    binding = _binding()

    with pytest.raises(LogicalProviderParameterBindingError, match="digest"):
        replace(binding, binding_sha256="f" * 64)
    with pytest.raises(
        LogicalProviderParameterBindingError,
        match="provider semantic parameters",
    ):
        compile_logical_provider_parameter_binding(
            raw_request_context=_capture_context(),
            logical_endpoint_name="league_game_log",
            logical_parameters=_LOGICAL_PARAMETERS,
            result_route_ids=binding.result_route_ids,
            provider_semantic_parameters=(_LOGICAL_PARAMETERS,),
        )
