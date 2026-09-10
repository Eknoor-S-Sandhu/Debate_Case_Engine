"""Explicit normalization rules for common debate heading vocabularies."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HeadingRuleMatch:
    """A normalized semantic heading match."""

    section_type: str
    normalized_heading: str
    outline_depth: int | None = None


@dataclass(frozen=True, slots=True)
class _LabelRule:
    section_type: str
    canonical_heading: str
    aliases: tuple[str, ...]


# Ordering matters where one label is a prefix of another.
_LABEL_RULES = (
    _LabelRule(
        "counter_interpretation",
        "Counter-Interpretation",
        ("counter interpretation", "counter-interpretation", "counter interp", "counter-interp"),
    ),
    _LabelRule(
        "competing_interpretations",
        "Competing Interpretations",
        ("competing interpretations",),
    ),
    _LabelRule(
        "counter_standards", "Counter-Standards", ("counter standards", "counter-standards")
    ),
    _LabelRule("internal_link", "Internal Link", ("internal links", "internal link", "il")),
    _LabelRule("value_criterion", "Value Criterion", ("value criterion", "criterion", "vc")),
    _LabelRule("weighing_mechanism", "Weighing Mechanism", ("weighing mechanism",)),
    _LabelRule("threshold_of_truth", "Threshold of Truth", ("threshold of truth",)),
    _LabelRule("role_of_the_ballot", "Role of the Ballot", ("role of the ballot", "rob")),
    _LabelRule("drop_the_argument", "Drop the Argument", ("drop the argument",)),
    _LabelRule("drop_the_team", "Drop the Team", ("drop the team",)),
    _LabelRule("theory_shell", "Theory Shell", ("theory shell",)),
    _LabelRule("advantage", "Advantage", ("advantage", "ad")),
    _LabelRule("disadvantage", "Disadvantage", ("disadvantage", "da")),
    _LabelRule("contention", "Contention", ("contention",)),
    _LabelRule("uniqueness", "Uniqueness", ("uniqueness", "uq")),
    _LabelRule("link", "Link", ("links", "link", "l")),
    _LabelRule("impact", "Impact", ("impacts", "impact", "impx")),
    _LabelRule("harms", "Harms", ("harms", "harm")),
    _LabelRule("solvency", "Solvency", ("solvency",)),
    _LabelRule("inherency", "Inherency", ("inherency",)),
    _LabelRule("counterplan", "Counterplan", ("counterplan", "counter plan", "cp")),
    _LabelRule(
        "plan",
        "Plan",
        (
            "plan text",
            "plan",
        ),
    ),
    _LabelRule("claim", "Claim", ("claims", "claim")),
    _LabelRule("warrant", "Warrant", ("warrants", "warrant")),
    _LabelRule("value", "Value", ("value",)),
    _LabelRule("problem", "Problem", ("problem",)),
    _LabelRule("mechanism", "Mechanism", ("mechanism",)),
    _LabelRule("comparative", "Comparative", ("comparative",)),
    _LabelRule("offense", "Offense", ("offense", "offence")),
    _LabelRule("defense", "Defense", ("defense", "defence")),
    _LabelRule("framework", "Framework", ("framework",)),
    _LabelRule("framing", "Framing", ("framing",)),
    _LabelRule("impact_calculus", "Impact Calculus", ("impact calculus",)),
    _LabelRule("observation", "Observation", ("observation",)),
    _LabelRule("definition", "Definition", ("definitions", "definition")),
    _LabelRule("interpretation", "Interpretation", ("interpretation", "interp")),
    _LabelRule("standards", "Standards", ("standards", "standard")),
    _LabelRule("voters", "Voters", ("voters", "voter")),
    _LabelRule("violation", "Violation", ("violations", "violation")),
    _LabelRule("reasonability", "Reasonability", ("reasonability",)),
    _LabelRule("alternative", "Alternative", ("alternative", "alt")),
    _LabelRule("permutation", "Permutation", ("permutation", "perm")),
    _LabelRule("root_cause", "Root Cause", ("root cause",)),
    _LabelRule("thesis", "Thesis", ("thesis",)),
    _LabelRule("answer", "Answer", ("responses", "response", "answers", "answer", "at", "a2")),
    _LabelRule("turn", "Turn", ("turns", "turn")),
)

_OUTLINE_PREFIX = re.compile(
    r"^\s*(?P<label>\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)[.)]\s+(?P<body>.+?)\s*$"
)
_ANSWER_WITH_TITLE = re.compile(
    r"^(?:at|a2|answer\s+to)(?:\s*[:\-–—]\s*|\s+)(?P<title>.+?)\s*$",
    re.IGNORECASE,
)
_NAMED_KRITIK = re.compile(r"^(?P<title>.+?)\s+(?:kritik|k)\s*:?\s*$", re.IGNORECASE)
_PREFIX_KRITIK = re.compile(
    r"^(?:kritik|k)(?:\s*[:\-–—]\s*(?P<title>.+))?\s*:?\s*$",
    re.IGNORECASE,
)
_NAMED_THEORY = re.compile(
    r"^(?P<title>.+?)\s+theory(?:\s+shell)?\s*:?\s*$",
    re.IGNORECASE,
)


def _outline_depth(label: str) -> int:
    if label.isdigit():
        return 1
    lowered = label.casefold()
    if all(character in "ivxlcdm" for character in lowered):
        return 3
    return 2


def _alias_pattern(alias: str) -> str:
    return r"\s+".join(re.escape(part) for part in alias.split())


def _match_label(text: str, rule: _LabelRule) -> tuple[str | None, str | None] | None:
    aliases = "|".join(_alias_pattern(alias) for alias in rule.aliases)
    pattern = re.compile(
        rf"^(?:{aliases})"
        r"(?:\s*(?P<number>\d+))?"
        r"(?:\s*[:\-–—]\s*(?P<title>.+?))?"
        r"\s*:?\s*$",
        re.IGNORECASE,
    )
    match = pattern.fullmatch(text)
    if not match:
        return None
    return match.group("number"), match.group("title")


def _normalized_heading(
    canonical: str,
    *,
    number: str | None = None,
    title: str | None = None,
) -> str:
    normalized = f"{canonical} {number}" if number else canonical
    return f"{normalized}: {title.strip()}" if title and title.strip() else normalized


def match_debate_heading(text: str) -> HeadingRuleMatch | None:
    """Return a normalized semantic match for an explicit debate heading."""
    collapsed = " ".join(text.strip().split())
    outline_match = _OUTLINE_PREFIX.fullmatch(collapsed)
    outline_depth = None
    if outline_match:
        outline_depth = _outline_depth(outline_match.group("label"))
        collapsed = outline_match.group("body")

    answer_match = _ANSWER_WITH_TITLE.fullmatch(collapsed)
    if answer_match:
        return HeadingRuleMatch(
            section_type="answer",
            normalized_heading=_normalized_heading(
                "Answer",
                title=answer_match.group("title"),
            ),
            outline_depth=outline_depth,
        )

    prefix_kritik = _PREFIX_KRITIK.fullmatch(collapsed)
    if prefix_kritik:
        return HeadingRuleMatch(
            section_type="kritik",
            normalized_heading=_normalized_heading(
                "Kritik",
                title=prefix_kritik.group("title"),
            ),
            outline_depth=outline_depth,
        )

    named_kritik = _NAMED_KRITIK.fullmatch(collapsed)
    if named_kritik:
        return HeadingRuleMatch(
            section_type="kritik",
            normalized_heading=_normalized_heading(
                "Kritik",
                title=named_kritik.group("title"),
            ),
            outline_depth=outline_depth,
        )

    named_theory = _NAMED_THEORY.fullmatch(collapsed)
    if named_theory and collapsed.casefold() != "theory shell":
        return HeadingRuleMatch(
            section_type="theory_shell",
            normalized_heading=_normalized_heading(
                "Theory Shell",
                title=named_theory.group("title"),
            ),
            outline_depth=outline_depth,
        )

    for rule in _LABEL_RULES:
        label_match = _match_label(collapsed, rule)
        if label_match is None:
            continue
        number, title = label_match
        return HeadingRuleMatch(
            section_type=rule.section_type,
            normalized_heading=_normalized_heading(
                rule.canonical_heading,
                number=number,
                title=title,
            ),
            outline_depth=outline_depth,
        )

    if outline_match:
        return HeadingRuleMatch(
            section_type="subpoint",
            normalized_heading=collapsed,
            outline_depth=outline_depth,
        )
    return None
