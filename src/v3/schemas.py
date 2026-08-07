from __future__ import annotations

from typing import Any, Literal, TypedDict


DOCUMENT_SCHEMA_VERSION = "dnf_document_v3.0"
NORMALIZED_DOCUMENT_SCHEMA_VERSION = "dnf_document_v3.1"
DOCUMENT_CONTENT_SCHEMA_VERSION = "dnf_document_content_v3.1"
NORMALIZED_CORPUS_MANIFEST_SCHEMA_VERSION = "dnf_normalized_corpus_manifest_v3.1"
CHUNK_SCHEMA_VERSION = "dnf_chunk_v3.0"
NORMALIZED_CHUNK_SCHEMA_VERSION = "dnf_chunk_v3.1"
CORPUS_MANIFEST_SCHEMA_VERSION = "dnf_corpus_manifest_v3.0"

DocumentStatus = Literal["current", "expired", "upcoming", "superseded", "unknown"]


class DocumentV3(TypedDict):
    document_id: str
    source_snapshot_id: str
    canonical_url: str
    source_kind: str
    authority: str
    title: str
    category_path: list[str]
    published_at: str | None
    valid_from: str | None
    valid_to: str | None
    revision_id: str
    supersedes_document_id: str | None
    status: DocumentStatus
    content_hash: str
    fetched_at: str
    parser_version: str
    raw_source_path: str


class NormalizedDocumentV3(DocumentV3):
    document_schema_version: str
    source_id: str
    listing_url: str
    canonical_url_kind: str
    lineage_id: str
    default_exposure: bool
    raw_content_hash: str
    normalized_text_hash: str
    visual_text_hash: str | None


class DocumentContentV3(TypedDict):
    content_schema_version: str
    document_id: str
    canonical_url: str
    content_hash: str
    text: str
    text_hash: str
    text_source: str
    parser_version: str
    raw_content_hash: str
    raw_source_path: str
    extraction_warnings: list[str]
    extraction_metadata: dict[str, Any]
    visual_evidence: dict[str, Any] | None


class ChunkV3(TypedDict):
    chunk_id: str
    parent_document_id: str
    heading_path: list[str]
    chunk_type: str
    display_text: str
    retrieval_text: str
    start_offset: int
    end_offset: int
    token_count: int
    entities: dict[str, list[str]]
    valid_from: str | None
    valid_to: str | None
    chunker_version: str


class NormalizedChunkV3(ChunkV3):
    chunk_schema_version: str
    source_id: str
    source_kind: str
    status: DocumentStatus
    default_exposure: bool
    offset_source: str
    evidence_quality: str
    review_required: bool
    token_count_method: str
    normalized_text_hash: str
    parent_content_hash: str
    chunk_index: int
    chunk_count: int
    max_chars: int
    overlap_chars: int


class TemporalPolicyRevisionV3(TypedDict):
    temporal_schema_version: str
    document_id: str
    lineage_id: str
    source_id: str
    source_kind: str
    canonical_url: str
    revision_id: str
    revision_ordinal: int
    published_at: str | None
    updated_at: str
    valid_from: str
    valid_to: str | None
    status: DocumentStatus
    is_current_revision: bool
    supersedes_document_id: str | None
    superseded_by: str | None
    last_verified_at: str
    default_exposure: bool


class TemporalRouteV3(TypedDict):
    temporal_router_schema_version: str
    query: str
    mode: Literal["current", "historical", "comparison"]
    as_of: str | None
    as_of_source: str | None
    needs_clarification: bool
    clarification_reason: str | None
    matched_markers: list[str]
    router_decision: str


class QuestionRouteV3(TypedDict):
    question_router_schema_version: str
    query: str
    intent: str
    matched_intents: list[str]
    required_sources: list[str]
    source_ids: list[str]
    source_kinds: list[str]
    time_scope: str
    temporal_as_of: str | None
    default_exposure_only: bool
    allowed_statuses: list[DocumentStatus]
    needs_decomposition: bool
    needs_clarification: bool
    clarification_reason: str | None
    route_action: str
    answerability: str
    answerability_reason: str
    routing_signals: dict[str, Any]


class DecomposedSubquestionV3(TypedDict):
    subquestion_id: str
    ordinal: int
    question: str
    relationship: str
    time_hint: str
    source_hint: str | None


class QuestionDecompositionV3(TypedDict):
    decomposition_schema_version: str
    parent_id: str
    parent_question: str
    strategy: str
    subquestions: list[DecomposedSubquestionV3]


class RawSnapshotManifestEntry(TypedDict):
    snapshot_id: str
    source_name: str
    source_path: str
    snapshot_path: str
    sha256: str
    fetched_at: str
    parser_version: str
    row_count: int
    byte_count: int


class CorpusManifestV3(TypedDict):
    manifest_schema_version: str
    manifest_id: str
    corpus_name: str
    snapshotter_version: str
    artifacts: list[RawSnapshotManifestEntry]
    total_row_count: int


DOCUMENT_REQUIRED_FIELDS = tuple(sorted(DocumentV3.__required_keys__))
NORMALIZED_DOCUMENT_REQUIRED_FIELDS = tuple(sorted(NormalizedDocumentV3.__required_keys__))
DOCUMENT_CONTENT_REQUIRED_FIELDS = tuple(sorted(DocumentContentV3.__required_keys__))
CHUNK_REQUIRED_FIELDS = tuple(sorted(ChunkV3.__required_keys__))
NORMALIZED_CHUNK_REQUIRED_FIELDS = tuple(sorted(NormalizedChunkV3.__required_keys__))
TEMPORAL_POLICY_REVISION_REQUIRED_FIELDS = tuple(
    sorted(TemporalPolicyRevisionV3.__required_keys__)
)
TEMPORAL_ROUTE_REQUIRED_FIELDS = tuple(sorted(TemporalRouteV3.__required_keys__))
QUESTION_ROUTE_REQUIRED_FIELDS = tuple(sorted(QuestionRouteV3.__required_keys__))
DECOMPOSED_SUBQUESTION_REQUIRED_FIELDS = tuple(
    sorted(DecomposedSubquestionV3.__required_keys__)
)
QUESTION_DECOMPOSITION_REQUIRED_FIELDS = tuple(
    sorted(QuestionDecompositionV3.__required_keys__)
)
RAW_SNAPSHOT_MANIFEST_ENTRY_REQUIRED_FIELDS = tuple(
    sorted(RawSnapshotManifestEntry.__required_keys__)
)
CORPUS_MANIFEST_REQUIRED_FIELDS = tuple(sorted(CorpusManifestV3.__required_keys__))
VALID_DOCUMENT_STATUSES = frozenset(DocumentStatus.__args__)


def missing_required_fields(row: dict[str, Any], required_fields: tuple[str, ...]) -> list[str]:
    """Return missing keys. Nullable schema fields are valid when explicitly present."""
    return sorted(field for field in required_fields if field not in row)
