"""Explicit live validation of a fixed public-motion corpus; no implicit user choice."""

import json
from pathlib import Path
from time import perf_counter
from typing import Annotated

import typer

from debate_engine.agents import RoundDirector
from debate_engine.agents.evaluation import select_architecture
from debate_engine.agents.strategy_provider import inference_ready, provider_settings
from debate_engine.config import ProviderName, Settings
from debate_engine.schemas.rounds import RoundInput

app = typer.Typer(add_completion=False)
CORPUS = Path(__file__).resolve().parents[1] / "docs/benchmarks/v1_motions.json"


def run_round(director, scenario, artifact_dir=None):
    start = perf_counter()
    row = {
        "id": scenario["id"],
        "status": "failed",
        "stage": "preparation",
        "inference_calls": [],
        "selected_architecture_id": 1,
        "quality_review": "pending_human_review",
    }
    try:
        context = RoundInput(
            **{k: v for k, v in scenario.items() if k != "id"},
            prep_rules={"internet_allowed": True},
        )
        packet = director.prepare(context)
        strategy = director.strategize(packet)
        results = [("strategy", strategy)]
        if strategy.status == "completed":
            evaluation = director.evaluate(packet, strategy)
            results.append(("evaluation", evaluation))
            if evaluation.status == "completed":
                # Fixed experimental choice, not a production auto-selection policy.
                selection = select_architecture(evaluation, 1)
                case = director.write_case(packet, strategy, selection)
                results.append(("case", case))
                if case.status == "completed":
                    chosen = next(
                        r.architecture for r in selection.repairs if r.architecture_id == 1
                    )
                    row["selection_preserved"] = case.selected_architecture_id == 1 and [
                        c.title for c in case.case.contentions
                    ] == [c.title for c in chosen.contentions]
                    row["word_count"] = case.word_count
                    row["word_limit"] = case.word_limit
        for name, result in results:
            row["inference_calls"].extend(c.model_dump() for c in result.inference_calls)
            row["stage"] = getattr(result, "stage", name)
            row["status"] = result.status
            row["warnings"] = result.warnings
        if row.get("selection_preserved") is False:
            row["status"] = "invalid_output"
            row["warnings"] = [
                *row.get("warnings", []),
                "Final case changed selected contention titles or order.",
            ]
        if artifact_dir is not None:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            for name, result in results:
                (artifact_dir / f"{name}.json").write_text(result.model_dump_json(indent=2))
            (artifact_dir / "packet.json").write_text(packet.model_dump_json(indent=2))
            if row["status"] == "completed":
                (artifact_dir / "case.md").write_text(case.markdown)
    except Exception:
        row["status"] = "failed"
        row["warnings"] = ["Round preparation or benchmark execution failed; raw error withheld."]
    row["elapsed_seconds"] = round(perf_counter() - start, 3)
    row["request_count"] = len(row["inference_calls"])
    return row


@app.command()
def benchmark(
    output: Annotated[Path, typer.Option(help="New output directory; contains private artifacts.")],
    provider: ProviderName = ProviderName.GEMINI,
    model: str | None = None,
    limit: Annotated[int, typer.Option(min=1, max=12)] = 12,
    timeout_seconds: Annotated[float, typer.Option(min=1, max=120)] = 60,
    live: Annotated[bool, typer.Option(help="Allow real provider requests and charges.")] = False,
):
    scenarios = json.loads(CORPUS.read_text())[:limit]
    if not live:
        typer.echo(f"Dry run: {len(scenarios)} rounds planned; no model or archive access.")
        return
    settings = Settings()
    settings.strategy.provider = provider
    settings.strategy.timeout_seconds = timeout_seconds
    if model is not None:
        getattr(settings, provider).model = model
    if not inference_ready(settings):
        typer.echo("Selected provider is not configured; no benchmark requests made.", err=True)
        raise typer.Exit(1)
    if output.exists():
        typer.echo("Choose a new output directory to preserve earlier benchmark runs.", err=True)
        raise typer.Exit(1)
    output.mkdir(parents=True)
    report = {
        "provider": provider.value,
        "model": provider_settings(settings).model,
        "planned_rounds": len(scenarios),
        "rows": [],
        "quality_review": "pending_human_review",
    }
    director = RoundDirector(settings)
    for scenario in scenarios:
        row = run_round(director, scenario, output / scenario["id"])
        report["rows"].append(row)
        (output / "report.json").write_text(json.dumps(report, indent=2))
        typer.echo(
            f"{row['id']}: {row['status']} ({row['stage']}); {row['request_count']} requests"
        )
        if any(
            c["error_code"]
            in {
                "authentication",
                "permission",
                "rate_limit_or_quota",
                "model_unavailable",
                "invalid_request",
            }
            for c in row["inference_calls"]
        ):
            typer.echo(
                "Stopping after a provider configuration/quota error; remaining rounds not run."
            )
            break
    if len(report["rows"]) != len(scenarios) or any(
        r["status"] != "completed" for r in report["rows"]
    ):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
