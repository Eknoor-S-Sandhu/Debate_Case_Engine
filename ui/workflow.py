"""Small, testable session-state transitions for the preparation UI."""

from time import monotonic, perf_counter

OUTPUTS = ("round_output", "strategy_output", "evaluation_output", "case_output")


def invalidate(state, from_stage):
    for key in OUTPUTS[OUTPUTS.index(from_stage) :]:
        state.pop(key, None)
    if from_stage != "case_output":
        state.pop("architecture_choice", None)
        state.pop("decision_started", None)
    if from_stage == "round_output":
        for key in (
            "prep_started",
            "prep_identity",
            "timings",
            "decision_seconds",
            "preparation_timings",
        ):
            state.pop(key, None)


def timed(state, stage, operation):
    start = perf_counter()
    try:
        return operation()
    finally:
        state.setdefault("timings", {}).setdefault(stage, []).append(perf_counter() - start)


def remaining_seconds(state, minutes, now=None):
    if "prep_started" not in state:
        return None
    elapsed = (monotonic() if now is None else now) - state["prep_started"]
    return max(0, int(minutes * 60 - elapsed))


def load_checkpoint(directory):
    """Load a saved local handoff only if its fingerprints agree; never call a provider."""
    from debate_engine.agents.evaluation import fingerprint
    from debate_engine.schemas.evaluation import EvaluationResult
    from debate_engine.schemas.rounds import KnowledgePacket
    from debate_engine.schemas.strategy import StrategyResult

    strategy_path = directory / "strategy.json"
    strategy = StrategyResult.model_validate_json(strategy_path.read_text())
    if strategy.status != "completed":
        raise ValueError("A completed strategy is required.")
    matching = []
    for path in sorted(directory.glob("packet*.json")):
        packet = KnowledgePacket.model_validate_json(path.read_text())
        if fingerprint(packet) == strategy.packet_fingerprint:
            matching.append(packet)
    if not matching:
        raise ValueError("No packet matches the saved strategy fingerprint.")
    result = {"round_output": matching[0], "strategy_output": strategy}
    evaluations = sorted(
        directory.glob("evaluation*.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    if evaluations:
        evaluation_path = evaluations[0]
        evaluation = EvaluationResult.model_validate_json(evaluation_path.read_text())
        if (
            evaluation.packet_fingerprint != strategy.packet_fingerprint
            or evaluation.strategy_fingerprint != fingerprint(strategy)
        ):
            raise ValueError("Evaluation does not match the saved strategy and packet.")
        result["evaluation_output"] = evaluation
    return result


def unresolved_findings(evaluation, architecture_id):
    """Join findings to repair statuses by stable IDs, never by display order."""
    critique = next((c for c in evaluation.critiques if c.architecture_id == architecture_id), None)
    repair = next((r for r in evaluation.repairs if r.architecture_id == architecture_id), None)
    if critique is None:
        return []
    responses = {r.finding_number: r for r in repair.responses} if repair else {}
    rows = []
    for number, finding in enumerate(critique.findings, 1):
        response = responses.get(number)
        if finding.severity == "high" and (response is None or response.status != "addressed"):
            rows.append((finding, response))
    return rows
