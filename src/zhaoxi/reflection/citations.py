"""Deterministic citation validation for generated Reflection content."""

from zhaoxi.reflection.models import EvidenceRef, ReflectionSection


class CitationError(ValueError):
    pass


class CitationValidator:
    def validate(
        self, sections: list[ReflectionSection], evidence: list[EvidenceRef]
    ) -> None:
        known = {item.evidence_id for item in evidence}
        for section in sections:
            for point in section.points:
                unknown = set(point.evidence_ids) - known
                if unknown:
                    raise CitationError(
                        f"Reflection 引用了不存在的 evidence：{', '.join(sorted(unknown))}"
                    )
                if point.statement_type == "question" and point.evidence_ids:
                    raise CitationError("question 不应伪装成 evidence-backed fact")
