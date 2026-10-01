"""ZhaoXi knowledge composition."""

import logging
from zhaoxi.config.settings import Settings
from zhaoxi.archive.service import ArchiveService
from zhaoxi.agenda import AgendaService, SQLiteAgendaStore
from zhaoxi.memory.embedding import provider_from_settings
from zhaoxi.memory.lifecycle import MemoryLifecyclePolicy
from zhaoxi.memory.retrieval import MemoryRetriever
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.current_cognition import CurrentCognitionStore, CurrentCognitionService
from zhaoxi.reflection.collector import ReflectionCollector
from zhaoxi.reflection.generator import ModelReflectionGenerator
from zhaoxi.reflection.periods import PeriodResolver
from zhaoxi.reflection.service import ReflectionService
from zhaoxi.reflection.sources import MemoryReflectionSource
from zhaoxi.reflection.sqlite import SQLiteReflectionRepository


def build_archive(settings: Settings, *, reindex: bool = True) -> ArchiveService | None:
    """Build the local archive without requiring model credentials."""
    if not settings.archive_enabled:
        return None
    service = ArchiveService(
        settings.archive_directory,
        settings.archive_db_path,
        search_top_k=settings.archive_search_top_k,
        context_max_chars=settings.archive_context_max_chars,
        max_document_chars=settings.archive_max_document_chars,
        chunk_max_chars=settings.archive_chunk_max_chars,
        chunk_overlap_chars=settings.archive_chunk_overlap_chars,
    )
    if reindex:
        report = service.reindex()
        if report.errors:
            logging.getLogger("ARCHIVE").warning(
                "archive indexed with %d document error(s)", len(report.errors)
            )
    return service


def build_knowledge_runtime(settings: Settings):
    memory_service = MemoryService(
        SQLiteMemoryRepository(settings.memory_db_path),
        MemoryLifecyclePolicy(
            importance_keep_threshold=settings.memory_importance_keep_threshold,
            activation_active_threshold=settings.memory_activation_active_threshold,
            activation_dormant_threshold=settings.memory_activation_dormant_threshold,
            activation_decay_per_day=settings.memory_activation_decay_per_day,
            activation_access_boost=settings.memory_activation_access_boost,
            cold_dormant_after_days=settings.memory_cold_dormant_after_days,
            dormant_archive_after_days=settings.memory_dormant_archive_after_days,
        ),
        embedding_provider=provider_from_settings(settings),
        cluster_max_members=settings.memory_cluster_max_members,
        cluster_embedding_enabled=settings.memory_cluster_embedding_enabled,
        cluster_match_threshold=settings.memory_cluster_match_threshold,
        cluster_merge_threshold=settings.memory_cluster_merge_threshold,
        edge_extraction_enabled=settings.memory_edge_extraction_enabled,
    )
    archive_service = build_archive(settings)
    memory_retriever = MemoryRetriever(
        memory_service,
        limit=settings.memory_retrieval_limit,
        max_chars=settings.memory_context_max_chars,
        per_cluster_limit=settings.memory_per_cluster_limit,
        max_hops=settings.memory_graph_max_hops,
        min_edge_weight=settings.memory_graph_min_edge_weight,
        archive=archive_service,
    )
    agenda_service = AgendaService(
        SQLiteAgendaStore(settings.agenda_db_path),
        timezone=settings.proactive_timezone,
        max_context_items=settings.agenda_max_context_items,
    )
    current_cognition_service = CurrentCognitionService(
        CurrentCognitionStore(settings.current_cognition_db_path,
                              legacy_stm_path=settings.short_term_memory_db_path),
        timezone=settings.proactive_timezone,
    )
    return memory_service, memory_retriever, agenda_service, current_cognition_service, archive_service


def build_reflection_runtime(settings: Settings, memory_service, tool_packages, package_capabilities, tool_package_errors, provider):
    reflection_service = None
    reflection_periods = None
    if settings.reflection_enabled:
        reflection_sources = [
            MemoryReflectionSource(
                memory_service,
                limit=settings.reflection_max_evidence,
                max_excerpt_chars=settings.reflection_max_excerpt_chars,
            )
        ]
        for package in tool_packages:
            if package_capabilities[package.package_id]["reflection_provider"] and hasattr(package, "reflection_sources"):
                try:
                    reflection_sources.extend(package.reflection_sources())
                except Exception as exc:
                    tool_package_errors.append({"source": f"{package.package_id}:reflection", "error": type(exc).__name__})
        reflection_service = ReflectionService(
            SQLiteReflectionRepository(settings.reflection_db_path),
            ReflectionCollector(
                reflection_sources,
                max_evidence=settings.reflection_max_evidence,
                max_evidence_chars=settings.reflection_max_evidence_chars,
            ),
            ModelReflectionGenerator(provider),
            prompt_version=settings.reflection_prompt_version,
        )
        reflection_periods = PeriodResolver(settings.reflection_timezone)
    return reflection_service, reflection_periods
