"""Debug deterministic hierarchical retrieval for one debate round."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from debate_engine.config import get_settings
from debate_engine.logging import configure_logging
from debate_engine.retrieval import HierarchicalRetriever
from debate_engine.schemas import (
    JudgeCategory,
    RetrievalCandidate,
    RetrievalRequest,
    RoundType,
    Side,
    SourceGroup,
)

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _print_candidate(
    candidate: RetrievalCandidate,
    *,
    show_scores: bool,
    show_text: bool,
) -> None:
    chunk = candidate.chunk
    typer.echo(
        f"{candidate.rank}. score={candidate.final_score:.4f} "
        f"support={candidate.support_level.value}"
    )
    typer.echo(
        f"   {chunk.source_group.value} / {chunk.source_file} / "
        f"{' > '.join(chunk.heading_path) or chunk.section_type}"
    )
    typer.echo(f"   section_type={chunk.section_type} chunk_level={chunk.chunk_level.value}")
    typer.echo(f"   chunk_id={chunk.chunk_id}")
    if candidate.parent_argument is not None:
        typer.echo(f"   parent_argument={candidate.parent_argument.chunk_id}")
    if candidate.related_children:
        typer.echo(
            "   related_children="
            + ", ".join(child.chunk_id for child in candidate.related_children)
        )
    if show_scores:
        typer.echo(
            "   scores: "
            f"semantic={candidate.semantic_score:.4f} "
            f"lexical={candidate.lexical_score:.4f} "
            f"concept={candidate.concept_score:.4f} "
            f"heading={candidate.heading_score:.4f} "
            f"base={candidate.base_score:.4f} "
            f"source={candidate.source_score:+.4f} "
            f"masterfile={candidate.masterfile_score:+.4f} "
            f"motion_similarity={candidate.motion_similarity_score:+.4f} "
            f"section_fit={candidate.section_fit_score:+.4f} "
            f"compatibility={candidate.compatibility_score:+.4f} "
            f"freshness={candidate.freshness_score:+.4f} "
            f"redundancy=-{candidate.redundancy_penalty:.4f}"
        )
        typer.echo(f"   reasons: {', '.join(candidate.reasons) or 'base relevance'}")
    if show_text:
        for line in chunk.text.splitlines():
            typer.echo(f"     | {line}")


@app.command()
def retrieve(
    motion: Annotated[str, typer.Argument(help="Round motion or explicit retrieval query.")],
    side: Annotated[str | None, typer.Option(help="aff, neg, gov, opp, or unknown.")] = None,
    round_type: Annotated[
        str | None,
        typer.Option(help="policy, value, fact, or unknown."),
    ] = None,
    judge: Annotated[
        str | None,
        typer.Option(help="tech, flow, flay, or fully_lay."),
    ] = None,
    judge_notes: Annotated[str | None, typer.Option(help="Preserved paradigm notes.")] = None,
    source_group: Annotated[
        str | None,
        typer.Option(help="Restrict to personal, past_case, or other."),
    ] = None,
    include_theory: Annotated[
        bool | None,
        typer.Option("--include-theory", help="Explicitly allow relevant personal theory."),
    ] = None,
    include_kritiks: Annotated[
        bool | None,
        typer.Option("--include-kritiks", help="Explicitly allow relevant personal Ks."),
    ] = None,
    arguments: Annotated[int | None, typer.Option(min=0, help="Full argument count.")] = None,
    modules: Annotated[int | None, typer.Option(min=0, help="Submodule count.")] = None,
    concept: Annotated[
        list[str] | None,
        typer.Option("--concept", help="Add an explicit search concept; repeatable."),
    ] = None,
    query: Annotated[
        list[str] | None,
        typer.Option("--query", help="Add an explicit retrieval query; repeatable."),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option(help="SQLite path. Defaults to configured storage."),
    ] = None,
    show_scores: Annotated[bool, typer.Option(help="Print component score breakdowns.")] = False,
    show_text: Annotated[bool, typer.Option(help="Print original SQLite chunk text.")] = False,
) -> None:
    """Retrieve full arguments and reusable modules without LLM reranking."""
    configure_logging()
    settings = get_settings()
    database_path = database or settings.storage.database_path
    if not database_path.exists():
        typer.echo(f"SQLite database does not exist at {database_path}.", err=True)
        raise typer.Exit(code=1)
    try:
        request = RetrievalRequest(
            motion=motion,
            side=Side(side) if side else None,
            round_type=RoundType(round_type) if round_type else None,
            judge_category=JudgeCategory(judge) if judge else None,
            judge_notes=judge_notes,
            source_group=SourceGroup(source_group) if source_group else None,
            include_theory=include_theory,
            include_kritiks=include_kritiks,
            desired_arguments=arguments,
            desired_submodules=modules,
            explicit_concepts=concept or [],
            user_queries=query or [],
        )
    except (ValueError, ValidationError) as exc:
        typer.echo(f"Invalid retrieval request: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    result = HierarchicalRetriever(settings, database=database_path).retrieve(request)
    typer.echo("GENERATED QUERIES")
    for index, generated in enumerate(result.generated_queries, start=1):
        typer.echo(f"{index}. [{generated.family.value}] {generated.text}")

    typer.echo("\nRELATED FULL ARGUMENTS")
    if not result.full_arguments:
        typer.echo("(none met the relevance threshold)")
    for candidate in result.full_arguments:
        _print_candidate(candidate, show_scores=show_scores, show_text=show_text)

    typer.echo("\nREUSABLE SUBMODULES")
    if not result.submodules:
        typer.echo("(none met the relevance threshold)")
    for candidate in result.submodules:
        _print_candidate(candidate, show_scores=show_scores, show_text=show_text)

    statistics = result.statistics
    typer.echo("\nRETRIEVAL STATISTICS")
    typer.echo(f"Semantic hits: {statistics.semantic_hits}")
    typer.echo(f"Lexical hits: {statistics.lexical_hits}")
    typer.echo(f"Merged candidates: {statistics.merged_candidates}")
    typer.echo(f"Ineligible candidates: {statistics.ineligible_candidates}")
    typer.echo(f"Duplicate candidates suppressed: {statistics.duplicate_candidates_suppressed}")
    typer.echo(f"Redundant candidates suppressed: {statistics.redundant_candidates_suppressed}")
    typer.echo(f"Below relevance threshold: {statistics.below_relevance_threshold}")
    for warning in result.warnings:
        typer.echo(f"Warning: {warning}")


if __name__ == "__main__":
    app()
