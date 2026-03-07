from dataclasses import dataclass
from typing import Any, List
from unittest.mock import MagicMock, patch

from worker.chunking import Chunk, ParsedSegment
from worker.config import WorkerConfig
from worker.db import DocumentRecord
from worker.processor import ChunkingResult, IngestProcessor, IngestTuning


@dataclass
class RecordingProgressTracker:
    calls: List[dict[str, Any]]

    def set(
        self,
        job_id: str,
        *,
        status: str,
        overall_progress: int,
        stage: str,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.calls.append(
            {
                "job_id": job_id,
                "status": status,
                "overall_progress": overall_progress,
                "stage": stage,
                "message": message,
                "details": details or {},
            }
        )


def _make_config(**overrides) -> WorkerConfig:
    base = dict(
        postgres_dsn="postgres://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
        ingest_queue_key="test_queue",
        poll_interval_seconds=1,
        worker_max_retries=2,
        s3_endpoint="localhost:9000",
        s3_access_key="test",
        s3_secret_key="test",
        s3_bucket="test",
        s3_use_ssl=False,
        qdrant_url="http://localhost:6333",
        qdrant_collection="test_chunks",
        embedding_dim=64,
        embedding_batch_size=16,
        embedding_batch_max_chars=24000,
        default_chunk_size=800,
        default_chunk_overlap=120,
        long_text_mode_enabled=True,
        long_text_threshold_chars=250000,
        long_text_chunk_size=3072,
        long_text_chunk_overlap=128,
        long_text_embedding_batch_size=64,
        long_text_embedding_batch_max_chars=192000,
        long_text_sparse_only_enabled=True,
        long_text_sparse_only_threshold_chars=2000000,
        long_text_sparse_chunk_chars=4096,
        long_text_sparse_chunk_overlap_chars=256,
        section_summary_threshold_chars=1000,
        section_summary_chars=2000,
        metadata_sampling_max_chars=120000,
        search_terms_max_per_chunk=64,
        embedding_provider="openai",
        embedding_base_url="",
        embedding_api_key="",
        embedding_model="",
        embedding_keep_alive="30m",
        embedding_timeout_seconds=120,
        llm_timeout_seconds=10,
        llm_max_retries=1,
        llm_retry_delay_milliseconds=100,
        metadata_enhancement_enabled=False,
        metadata_max_keywords=5,
    )
    base.update(overrides)
    return WorkerConfig(**base)


def test_select_ingest_tuning_uses_section_dense_sparse_profile() -> None:
    processor = IngestProcessor(_make_config(section_summary_threshold_chars=1000))

    tuning = processor._select_ingest_tuning(5000)

    assert tuning.profile == "section_dense_sparse"
    assert tuning.index_mode == "section_dense_sparse"
    assert tuning.chunk_unit == "chars"
    assert tuning.dense_chunk_embeddings_enabled is False
    assert tuning.dense_section_embeddings_enabled is True


def test_select_ingest_tuning_uses_sparse_only_profile() -> None:
    processor = IngestProcessor(
        _make_config(
            section_summary_threshold_chars=1000,
            long_text_sparse_only_enabled=True,
            long_text_sparse_only_threshold_chars=2000,
        )
    )

    tuning = processor._select_ingest_tuning(5000)

    assert tuning.profile == "sparse_only"
    assert tuning.index_mode == "sparse_only"
    assert tuning.chunk_unit == "chars"
    assert tuning.embedding_batch_size == 0
    assert tuning.embedding_batch_max_chars == 0
    assert tuning.dense_chunk_embeddings_enabled is False
    assert tuning.dense_section_embeddings_enabled is False


def test_select_ingest_tuning_uses_long_text_dense_profile() -> None:
    processor = IngestProcessor(
        _make_config(
            section_summary_threshold_chars=900000,
            long_text_threshold_chars=1000,
            long_text_chunk_size=3072,
            long_text_chunk_overlap=128,
            long_text_embedding_batch_size=64,
            long_text_embedding_batch_max_chars=192000,
        )
    )

    tuning = processor._select_ingest_tuning(5000)

    assert tuning.profile == "long_text_dense"
    assert tuning.index_mode == "dense"
    assert tuning.chunk_unit == "tokens"
    assert tuning.chunk_size == 3072
    assert tuning.chunk_overlap == 128
    assert tuning.embedding_batch_size == 64
    assert tuning.embedding_batch_max_chars == 192000
    assert tuning.dense_chunk_embeddings_enabled is True
    assert tuning.dense_section_embeddings_enabled is False


@patch("worker.processor.S3Store")
@patch("worker.processor.EmbeddingClient")
@patch("worker.processor.DB")
def test_stage_embed_creates_section_vectors_and_sparse_chunk_rows(
    mock_db_cls,
    mock_embed_cls,
    mock_s3_cls,
) -> None:
    tracker = RecordingProgressTracker(calls=[])
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db
    mock_conn = MagicMock()
    mock_db.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_db.connect.return_value.__exit__ = MagicMock(return_value=False)
    mock_db.is_job_cancelled.return_value = False

    mock_embed = MagicMock()
    mock_embed_cls.return_value = mock_embed
    mock_embed.embed_batch.return_value = [[0.1] * 64, [0.2] * 64]

    processor = IngestProcessor(_make_config(), progress_tracker=tracker)
    doc = DocumentRecord(id="d1", corpus_id="c1", file_name="test.txt", file_type="txt", storage_key="key")
    sections = [
        ParsedSegment(text="第01章\n第一段", page_or_loc="text:1", section_index=1, section_title="第01章", char_start=0, char_end=8, kind="section"),
        ParsedSegment(text="第02章\n第二段", page_or_loc="text:2", section_index=2, section_title="第02章", char_start=9, char_end=17, kind="section"),
    ]
    chunks = [
        Chunk(chunk_index=0, text="第一段内容", page_or_loc="text:1", token_count=4, section_index=1, section_title="第01章", normalized_text="第一段内容", search_terms=("第一段",), char_count=4),
        Chunk(chunk_index=1, text="第二段内容", page_or_loc="text:2", token_count=4, section_index=2, section_title="第02章", normalized_text="第二段内容", search_terms=("第二段",), char_count=4),
    ]
    tuning = IngestTuning(
        profile="section_dense_sparse",
        index_mode="section_dense_sparse",
        chunk_unit="chars",
        source_text_chars=5000,
        chunk_size=4096,
        chunk_overlap=256,
        embedding_batch_size=8,
        embedding_batch_max_chars=64000,
        dense_chunk_embeddings_enabled=False,
        dense_section_embeddings_enabled=True,
    )

    vector_points, db_sections, db_chunks = processor._stage_embed(
        "j1",
        doc,
        ChunkingResult(chunks=chunks, tuning=tuning, sections=sections),
    )

    assert len(vector_points) == 2
    assert {point.payload["point_type"] for point in vector_points} == {"section_summary"}
    assert len(db_sections) == 2
    assert all(section.qdrant_point_id for section in db_sections)
    assert len(db_chunks) == 2
    assert all(chunk.qdrant_point_id.startswith("sparse:d1:") for chunk in db_chunks)
    assert any(call["stage"] == "embedding" for call in tracker.calls)


@patch("worker.processor.S3Store")
@patch("worker.processor.EmbeddingClient")
@patch("worker.processor.DB")
def test_stage_embed_skips_dense_embedding_for_sparse_only_profile(
    mock_db_cls,
    mock_embed_cls,
    mock_s3_cls,
) -> None:
    tracker = RecordingProgressTracker(calls=[])
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db
    mock_conn = MagicMock()
    mock_db.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_db.connect.return_value.__exit__ = MagicMock(return_value=False)
    mock_db.is_job_cancelled.return_value = False

    mock_embed = MagicMock()
    mock_embed_cls.return_value = mock_embed

    processor = IngestProcessor(_make_config(), progress_tracker=tracker)
    doc = DocumentRecord(id="d1", corpus_id="c1", file_name="test.txt", file_type="txt", storage_key="key")
    sections = [
        ParsedSegment(text="section body", page_or_loc="text:1", section_index=1, section_title="section 1"),
    ]
    chunks = [
        Chunk(
            chunk_index=0,
            text="alpha beta gamma",
            page_or_loc="text:1",
            token_count=3,
            section_index=1,
            section_title="section 1",
            normalized_text="alpha beta gamma",
            search_terms=("alpha", "beta"),
            char_count=16,
        ),
    ]
    tuning = IngestTuning(
        profile="sparse_only",
        index_mode="sparse_only",
        chunk_unit="chars",
        source_text_chars=3000000,
        chunk_size=4096,
        chunk_overlap=256,
        embedding_batch_size=0,
        embedding_batch_max_chars=0,
        dense_chunk_embeddings_enabled=False,
        dense_section_embeddings_enabled=False,
    )

    vector_points, db_sections, db_chunks = processor._stage_embed(
        "j1",
        doc,
        ChunkingResult(chunks=chunks, tuning=tuning, sections=sections),
    )

    assert vector_points == []
    assert len(db_sections) == 1
    assert len(db_chunks) == 1
    assert db_chunks[0].qdrant_point_id == "sparse:d1:0"
    mock_embed.embed_batch.assert_not_called()
    assert any(call["message"] == "no dense embedding required" for call in tracker.calls)


@patch("worker.processor.parse_document")
@patch("worker.processor.S3Store")
@patch("worker.processor.EmbeddingClient")
@patch("worker.processor.DB")
def test_stage_parse_uses_sampled_metadata_enhancement(
    mock_db_cls,
    mock_embed_cls,
    mock_s3_cls,
    mock_parse_document,
) -> None:
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db
    mock_conn = MagicMock()
    mock_db.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_db.connect.return_value.__exit__ = MagicMock(return_value=False)
    mock_db.is_job_cancelled.return_value = False

    mock_parse_document.return_value = [
        ParsedSegment(text="第01章\n第一段", page_or_loc="text:1", section_index=1, section_title="第01章"),
        ParsedSegment(text="第02章\n第二段", page_or_loc="text:2", section_index=2, section_title="第02章"),
    ]

    processor = IngestProcessor(_make_config(metadata_enhancement_enabled=True))
    processor._metadata_enhancer = MagicMock()

    processor._stage_parse("j1", __import__("pathlib").Path("dummy.txt"), "txt")

    processor._metadata_enhancer.enhance_segments.assert_called_once()
