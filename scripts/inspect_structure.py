"""Parse one debate file and print its detected section tree."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from debate_engine.ingestion import detect_structure, parse_document
from debate_engine.logging import configure_logging
from debate_engine.schemas import StructuredSection

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _print_section(
    section: StructuredSection,
    *,
    depth: int,
    show_confidence: bool,
    show_text: bool,
    max_depth: int | None,
) -> None:
    if max_depth is not None and depth > max_depth:
        return

    indent = "  " * (depth - 1)
    heading = (section.original_heading or section.normalized_heading or "(untitled)").strip()
    confidence = f" confidence={section.confidence:.2f}" if show_confidence else ""
    typer.echo(f"{indent}{heading} [{section.section_type}]{confidence}")

    if show_text and section.text:
        text_indent = "  " * depth
        for line in section.text.splitlines():
            typer.echo(f"{text_indent}| {line}")

    for child in section.children:
        _print_section(
            child,
            depth=depth + 1,
            show_confidence=show_confidence,
            show_text=show_text,
            max_depth=max_depth,
        )


@app.command()
def inspect(
    source: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="A supported debate document.",
        ),
    ],
    show_confidence: Annotated[
        bool,
        typer.Option(help="Show confidence beside each detected section."),
    ] = False,
    show_text: Annotated[
        bool,
        typer.Option(help="Show direct body text under each section."),
    ] = False,
    max_depth: Annotated[
        int | None,
        typer.Option(min=1, help="Hide sections deeper than this tree level."),
    ] = None,
) -> None:
    """Print deterministic debate structure without writing any files."""
    configure_logging()
    parsed = parse_document(source)
    structured = detect_structure(parsed)

    typer.echo(f"Source: {structured.source_path}")
    typer.echo(f"Parse status: {parsed.parse_status.value}")
    typer.echo(f"Title: {structured.title or '(unknown)'}")
    typer.echo(f"Overall confidence: {structured.overall_structure_confidence:.2f}")
    typer.echo("")

    if structured.sections:
        for section in structured.sections:
            _print_section(
                section,
                depth=1,
                show_confidence=show_confidence,
                show_text=show_text,
                max_depth=max_depth,
            )
    else:
        typer.echo("(no reliable structure detected)")

    if structured.unstructured_text.strip():
        typer.echo("\nUnstructured/orphan text preserved:")
        for line in structured.unstructured_text.splitlines():
            typer.echo(f"  | {line}")

    if structured.detection_warnings:
        typer.echo("\nDetection warnings:")
        for warning in structured.detection_warnings:
            typer.echo(f"  - {warning}")


if __name__ == "__main__":
    app()
