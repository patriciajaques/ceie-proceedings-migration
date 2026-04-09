from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from .nodes import (
    node_build_articles_from_site,
    node_download_pdfs,
    node_enrich_merge,
    node_enrich_one_article,
    node_enrich_prepare,
    node_extract_sections_and_write_csv,
    node_fetch_website_articles,
    node_field_merge,
    node_field_one_article,
    node_field_prepare,
    node_infer_doi_prefix,
    node_skip_completed_articles,
    node_validate_year,
    route_after_skip_articles,
    route_enrich_articles,
    route_field_completion,
)
from .state import MigrationState


def build_migration_graph(*, migrator, checkpointer: Any | None = None) -> Any:
    """
    Build the central migration graph.

    The returned callable executes the full pipeline and returns a final state.

    Enrichment from PDFs and field completion use map-reduce (Send per article) so a
    checkpointer can persist progress after each article super-step.
    """

    graph = StateGraph(MigrationState)

    graph.add_node(
        "fetch_website_articles", lambda s: node_fetch_website_articles(s, migrator)
    )
    graph.add_node("validate_year", lambda s: node_validate_year(s, migrator))
    graph.add_node("download_pdfs", lambda s: node_download_pdfs(s, migrator))
    graph.add_node("infer_doi_prefix", lambda s: node_infer_doi_prefix(s, migrator))
    graph.add_node(
        "extract_sections", lambda s: node_extract_sections_and_write_csv(s, migrator)
    )
    graph.add_node("build_articles", node_build_articles_from_site)
    graph.add_node(
        "skip_completed_articles",
        lambda s: node_skip_completed_articles(s, migrator),
    )
    graph.add_node("enrich_prepare", lambda s: node_enrich_prepare(s, migrator))
    graph.add_node(
        "enrich_one_article", lambda s: node_enrich_one_article(s, migrator)
    )
    graph.add_node("enrich_merge", lambda s: node_enrich_merge(s, migrator))
    graph.add_node("field_prepare", lambda s: node_field_prepare(s, migrator))
    graph.add_node(
        "field_one_article", lambda s: node_field_one_article(s, migrator)
    )
    graph.add_node("field_merge", lambda s: node_field_merge(s, migrator))

    graph.set_entry_point("fetch_website_articles")
    graph.add_edge("fetch_website_articles", "validate_year")
    graph.add_edge("validate_year", "download_pdfs")
    graph.add_edge("download_pdfs", "infer_doi_prefix")
    graph.add_edge("infer_doi_prefix", "extract_sections")
    graph.add_edge("extract_sections", "build_articles")
    graph.add_edge("build_articles", "skip_completed_articles")
    graph.add_conditional_edges(
        "skip_completed_articles",
        route_after_skip_articles,
        {
            "enrich_prepare": "enrich_prepare",
            "enrich_merge": "enrich_merge",
        },
    )
    graph.add_conditional_edges(
        "enrich_prepare",
        route_enrich_articles,
        ["enrich_one_article", "enrich_merge"],
    )
    graph.add_edge("enrich_one_article", "enrich_merge")
    graph.add_edge("enrich_merge", "field_prepare")
    graph.add_conditional_edges(
        "field_prepare",
        route_field_completion,
        ["field_one_article", "field_merge"],
    )
    graph.add_edge("field_one_article", "field_merge")
    graph.add_edge("field_merge", END)

    return graph.compile(checkpointer=checkpointer)
