from __future__ import annotations

import pytest

from nbadb.contracts.public_data_disposition import (
    PRIVATE_RAW_AUTHORITY_RELATIONS,
    PUBLIC_DATA_DISPOSITION_SCHEMA_VERSION,
    RESERVED_ENVELOPE_PATHS,
    PublicDataDispositionError,
    PublicDataDispositionV1,
    PublicRelationDispositionV1,
    PublicResourceDispositionV1,
)

_SHA = "a" * 64
_OTHER_SHA = "b" * 64
_TREE_SHA = "c" * 64
_INVENTORY_SHA = "d" * 64


def _relation(**overrides: object) -> PublicRelationDispositionV1:
    values: dict[str, object] = {
        "table_name": "raw_nba_api_result_cell",
        "category": "raw-w2-structured",
        "ordered_columns": ("cell_path", "record_sha256", "value_sha256"),
        "physical_types": ("VARCHAR", "VARCHAR", "VARCHAR"),
    }
    values.update(overrides)
    return PublicRelationDispositionV1.build(**values)  # type: ignore[arg-type]


def _resource(**overrides: object) -> PublicResourceDispositionV1:
    values: dict[str, object] = {
        "path": "star/dim_game.parquet",
        "size_bytes": 4096,
        "sha256": _OTHER_SHA,
        "media_type": "application/vnd.apache.parquet",
        "relation_name": None,
    }
    values.update(overrides)
    return PublicResourceDispositionV1(**values)  # type: ignore[arg-type]


def _disposition(
    *,
    relations: list[PublicRelationDispositionV1] | None = None,
    resources: list[PublicResourceDispositionV1] | None = None,
) -> PublicDataDispositionV1:
    return PublicDataDispositionV1.build(
        candidate_tree_sha256=_TREE_SHA,
        candidate_inventory_sha256=_INVENTORY_SHA,
        relation_entries=relations if relations is not None else [_relation()],
        resource_entries=resources if resources is not None else [_resource()],
    )


class TestRelationDisposition:
    def test_valid_relation_round_trips(self) -> None:
        relation = _relation()
        parsed = PublicRelationDispositionV1.from_payload(relation.to_payload())
        assert parsed == relation
        assert parsed.schema_sha256 == relation.schema_sha256

    @pytest.mark.parametrize(
        "columns",
        [
            ("value_sha256", "cell_path", "record_sha256"),
            ("cell_path", "cell_path", "record_sha256"),
        ],
    )
    def test_rejects_unsorted_or_duplicate_columns(self, columns: tuple[str, ...]) -> None:
        with pytest.raises(PublicDataDispositionError):
            _relation(ordered_columns=columns)

    def test_rejects_column_type_length_mismatch(self) -> None:
        with pytest.raises(PublicDataDispositionError, match="same length"):
            _relation(physical_types=("VARCHAR", "VARCHAR"))

    @pytest.mark.parametrize(
        "physical_type",
        ["BINARY", "blob", "BYTES", "bytea", "varbinary", "large_binary"],
    )
    def test_rejects_binary_physical_types(self, physical_type: str) -> None:
        with pytest.raises(PublicDataDispositionError, match="binary physical type"):
            _relation(physical_types=("VARCHAR", physical_type, "VARCHAR"))

    def test_rejects_non_snake_table_name(self) -> None:
        with pytest.raises(PublicDataDispositionError, match="snake_case"):
            _relation(table_name="RawNbaApiResultCell")

    @pytest.mark.parametrize("private", PRIVATE_RAW_AUTHORITY_RELATIONS)
    def test_rejects_private_relation_entry(self, private: str) -> None:
        with pytest.raises(PublicDataDispositionError, match="private raw authority"):
            _relation(table_name=private)

    def test_rejects_private_substring_table_name(self) -> None:
        with pytest.raises(PublicDataDispositionError, match="private raw authority"):
            _relation(table_name="raw_nba_api_result_occurrence_export")

    def test_schema_drift_fails_closed(self) -> None:
        # Same shape (sorted, duplicate-free, matching length) but a renamed
        # column: only the recomputed schema digest can catch it.
        payload = _relation().to_payload()
        payload["ordered_columns"] = ["cell_path", "record_sha256", "value_digest"]
        with pytest.raises(PublicDataDispositionError, match="drift"):
            PublicRelationDispositionV1.from_payload(payload)

    def test_rejects_missing_or_extra_payload_keys(self) -> None:
        payload = _relation().to_payload()
        del payload["category"]
        with pytest.raises(PublicDataDispositionError, match="missing"):
            PublicRelationDispositionV1.from_payload(payload)
        payload = _relation().to_payload()
        payload["alias_for"] = "something"
        with pytest.raises(PublicDataDispositionError, match="extra"):
            PublicRelationDispositionV1.from_payload(payload)

    def test_rejects_wrong_schema_version(self) -> None:
        payload = _relation().to_payload()
        payload["schema_version"] = PUBLIC_DATA_DISPOSITION_SCHEMA_VERSION + 1
        with pytest.raises(PublicDataDispositionError, match="schema version"):
            PublicRelationDispositionV1.from_payload(payload)


class TestResourceDisposition:
    def test_valid_resource_round_trips(self) -> None:
        resource = _resource()
        parsed = PublicResourceDispositionV1.from_payload(resource.to_payload())
        assert parsed == resource

    @pytest.mark.parametrize(
        "path",
        [
            "/absolute/star.parquet",
            "star\\windows.parquet",
            "../escape.parquet",
            "star/../escape.parquet",
            "./star.parquet",
            "star//double.parquet",
            "star/",
            "",
        ],
    )
    def test_rejects_non_canonical_paths(self, path: str) -> None:
        with pytest.raises(PublicDataDispositionError):
            _resource(path=path)

    @pytest.mark.parametrize("private", PRIVATE_RAW_AUTHORITY_RELATIONS)
    def test_rejects_private_relation_name(self, private: str) -> None:
        with pytest.raises(PublicDataDispositionError, match="private raw authority"):
            _resource(relation_name=private)

    def test_rejects_private_reference_in_path(self) -> None:
        with pytest.raises(PublicDataDispositionError, match="private raw authority"):
            _resource(path="raw/raw_nba_api_parser_input_object.parquet")
        with pytest.raises(PublicDataDispositionError, match="private raw authority"):
            _resource(path=f"evidence/{PRIVATE_RAW_AUTHORITY_RELATIONS[1]}.json")

    def test_rejects_bad_digest_size_and_media_type(self) -> None:
        with pytest.raises(PublicDataDispositionError, match="sha256"):
            _resource(sha256=_OTHER_SHA[:63])
        with pytest.raises(PublicDataDispositionError, match="media_type"):
            _resource(media_type="parquet")
        with pytest.raises(PublicDataDispositionError, match="media_type"):
            _resource(media_type="")

    def test_rejects_negative_or_bool_size(self) -> None:
        with pytest.raises(PublicDataDispositionError, match="non-negative"):
            _resource(size_bytes=-1)
        with pytest.raises(PublicDataDispositionError, match="non-negative"):
            _resource(size_bytes=True)


class TestDisposition:
    def test_valid_disposition_round_trips(self) -> None:
        disposition = _disposition()
        parsed = PublicDataDispositionV1.from_payload(disposition.to_payload())
        assert parsed == disposition
        assert parsed.compute_disposition_sha256() == disposition.disposition_sha256

    def test_reserved_envelope_is_exactly_fixed(self) -> None:
        disposition = _disposition()
        assert disposition.reserved_envelope_paths == RESERVED_ENVELOPE_PATHS
        with pytest.raises(PublicDataDispositionError, match="fixed staged publication"):
            PublicDataDispositionV1(
                candidate_tree_sha256=_TREE_SHA,
                candidate_inventory_sha256=_INVENTORY_SHA,
                relation_entries=(_relation(),),
                resource_entries=(_resource(),),
                reserved_envelope_paths=("dataset-metadata.json",),
                disposition_sha256=disposition.disposition_sha256,
            )

    @pytest.mark.parametrize("reserved", RESERVED_ENVELOPE_PATHS)
    def test_resource_may_not_claim_reserved_envelope_path(self, reserved: str) -> None:
        resources = sorted(
            [_resource(), _resource(path=reserved, media_type="application/json")],
            key=lambda resource: resource.path,
        )
        with pytest.raises(PublicDataDispositionError, match="reserved envelope path"):
            _disposition(resources=resources)

    def test_rejects_duplicate_resource_paths(self) -> None:
        with pytest.raises(PublicDataDispositionError, match="duplicate"):
            _disposition(resources=[_resource(), _resource()])

    def test_rejects_overlapping_file_parent_paths(self) -> None:
        with pytest.raises(PublicDataDispositionError, match="file-parent"):
            _disposition(
                resources=[
                    _resource(path="star/data"),
                    _resource(path="star/data/dim_game.parquet"),
                ]
            )

    def test_rejects_unordered_entries(self) -> None:
        with pytest.raises(PublicDataDispositionError, match="strictly ordered"):
            _disposition(
                resources=[
                    _resource(path="zeta/z.parquet"),
                    _resource(path="alpha/a.parquet"),
                ]
            )

    def test_rejects_duplicate_relation_tables(self) -> None:
        with pytest.raises(PublicDataDispositionError, match="duplicate"):
            _disposition(relations=[_relation(), _relation()])

    def test_disposition_digest_tamper_fails_closed(self) -> None:
        disposition = _disposition()
        with pytest.raises(PublicDataDispositionError, match="drift"):
            PublicDataDispositionV1(
                candidate_tree_sha256=_TREE_SHA,
                candidate_inventory_sha256=_INVENTORY_SHA,
                relation_entries=disposition.relation_entries,
                resource_entries=disposition.resource_entries,
                reserved_envelope_paths=RESERVED_ENVELOPE_PATHS,
                disposition_sha256=_SHA,
            )

    def test_entry_mutation_fails_digest_verification(self) -> None:
        payload = _disposition().to_payload()
        payload["resource_entries"][0]["size_bytes"] = 8192
        with pytest.raises(PublicDataDispositionError, match="drift"):
            PublicDataDispositionV1.from_payload(payload)

    def test_digest_is_deterministic_across_builds(self) -> None:
        first = _disposition()
        second = _disposition()
        assert first.disposition_sha256 == second.disposition_sha256
        assert (
            first.disposition_sha256
            != _disposition(resources=[_resource(size_bytes=8192)]).disposition_sha256
        )

    def test_rejects_missing_and_extra_disposition_keys(self) -> None:
        payload = _disposition().to_payload()
        del payload["candidate_tree_sha256"]
        with pytest.raises(PublicDataDispositionError, match="missing"):
            PublicDataDispositionV1.from_payload(payload)
        payload = _disposition().to_payload()
        payload["notes"] = "advisory"
        with pytest.raises(PublicDataDispositionError, match="extra"):
            PublicDataDispositionV1.from_payload(payload)

    def test_rejects_wrong_disposition_schema_version(self) -> None:
        payload = _disposition().to_payload()
        payload["schema_version"] = PUBLIC_DATA_DISPOSITION_SCHEMA_VERSION + 1
        with pytest.raises(PublicDataDispositionError, match="schema version"):
            PublicDataDispositionV1.from_payload(payload)

    def test_rejects_non_entry_instances(self) -> None:
        with pytest.raises(PublicDataDispositionError, match="instances"):
            PublicDataDispositionV1(
                candidate_tree_sha256=_TREE_SHA,
                candidate_inventory_sha256=_INVENTORY_SHA,
                relation_entries=({"table_name": "x"},),  # type: ignore[arg-type]
                resource_entries=(_resource(),),
                reserved_envelope_paths=RESERVED_ENVELOPE_PATHS,
                disposition_sha256=_SHA,
            )

    def test_empty_entries_round_trip(self) -> None:
        disposition = _disposition(relations=[], resources=[])
        parsed = PublicDataDispositionV1.from_payload(disposition.to_payload())
        assert parsed == disposition
        assert parsed.relation_entries == ()
        assert parsed.resource_entries == ()
