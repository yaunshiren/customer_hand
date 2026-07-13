from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ProductResolutionStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    RESOLVED = "RESOLVED"
    CONFLICT = "CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"


class ProductSupportLevel(str, Enum):
    STANDARD = "standard"
    LIMITED = "limited"


class ProductEvidence(BaseModel):
    """One catalog alias match, without retaining the complete user message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    matched_alias: NonEmptyText
    model_id: NonEmptyText
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def _validate_span(self) -> "ProductEvidence":
        if self.end <= self.start:
            raise ValueError("evidence end must be greater than start")
        return self


class ProductContext(BaseModel):
    """Current-turn product resolution result with enforced state invariants."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resolution_status: ProductResolutionStatus
    model_id: NonEmptyText | None = None
    matched_models: tuple[NonEmptyText, ...] = ()
    support_level: ProductSupportLevel | None = None
    unsupported_mentions: tuple[NonEmptyText, ...] = ()
    evidence: tuple[ProductEvidence, ...] = ()

    @model_validator(mode="after")
    def _validate_state_invariants(self) -> "ProductContext":
        if len(set(self.matched_models)) != len(self.matched_models):
            raise ValueError("matched_models must not contain duplicates")
        if len(set(self.unsupported_mentions)) != len(self.unsupported_mentions):
            raise ValueError("unsupported_mentions must not contain duplicates")

        declared_ids = set(self.matched_models) | set(self.unsupported_mentions)
        evidence_ids = {item.model_id for item in self.evidence}
        if evidence_ids != declared_ids:
            raise ValueError("evidence model ids must exactly match declared product mentions")

        if self.resolution_status is ProductResolutionStatus.UNKNOWN:
            if (
                self.model_id is not None
                or self.matched_models
                or self.unsupported_mentions
                or self.support_level is not None
                or self.evidence
            ):
                raise ValueError("UNKNOWN must not contain product resolution data")
            return self

        if self.resolution_status is ProductResolutionStatus.RESOLVED:
            if self.model_id is None:
                raise ValueError("RESOLVED requires model_id")
            if self.matched_models != (self.model_id,):
                raise ValueError("RESOLVED matched_models must contain only model_id")
            if self.unsupported_mentions:
                raise ValueError("RESOLVED must not contain unsupported mentions")
            if self.support_level is None:
                raise ValueError("RESOLVED requires support_level")
            if not self.evidence:
                raise ValueError("RESOLVED requires evidence")
            return self

        if self.resolution_status is ProductResolutionStatus.CONFLICT:
            has_supported_conflict = len(self.matched_models) >= 2
            has_mixed_conflict = bool(self.matched_models and self.unsupported_mentions)
            if self.model_id is not None or self.support_level is not None:
                raise ValueError("CONFLICT must not resolve a model or support level")
            if not (has_supported_conflict or has_mixed_conflict):
                raise ValueError("CONFLICT requires multiple supported models or mixed support")
            if not self.evidence:
                raise ValueError("CONFLICT requires evidence")
            return self

        if self.resolution_status is ProductResolutionStatus.UNSUPPORTED:
            if self.model_id is not None or self.matched_models or self.support_level is not None:
                raise ValueError("UNSUPPORTED must not contain supported resolution data")
            if not self.unsupported_mentions:
                raise ValueError("UNSUPPORTED requires an unsupported mention")
            if not self.evidence:
                raise ValueError("UNSUPPORTED requires evidence")
            return self

        raise ValueError(f"unhandled resolution status: {self.resolution_status}")
