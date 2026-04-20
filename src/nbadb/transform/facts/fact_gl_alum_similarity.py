from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactGlAlumSimilarityTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_gl_alum_similarity"
    depends_on: ClassVar[list[str]] = ["stg_gl_alum_box_score_similarity_score"]

    _SQL: ClassVar[str] = """SELECT * FROM stg_gl_alum_box_score_similarity_score"""
