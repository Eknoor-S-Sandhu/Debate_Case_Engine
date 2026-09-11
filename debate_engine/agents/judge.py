"""Conservative, inspectable paradigm parsing with explicit-input precedence."""

import re

from debate_engine.schemas import JudgeCategory
from debate_engine.schemas.adaptation import JudgeProfile

_GUIDANCE = {
    JudgeCategory.TECH: [
        "Explain deep causal mechanisms and technical concessions.",
        "Prioritize warranted preempts and explicit comparative weighing.",
        "Consider existing theory/K material only when eligible and strategically relevant.",
    ],
    JudgeCategory.FLOW: [
        "Use clear organization, strong warrants, and explicit weighing.",
        "Keep technical substance tied to conventional, well-explained offense.",
    ],
    JudgeCategory.FLAY: [
        "Explain mechanisms intuitively and connect them to concrete outcomes.",
        "Avoid reliance on obscure assumptions; define necessary terminology.",
    ],
    JudgeCategory.FULLY_LAY: [
        "Use accessible causal stories and concrete examples.",
        "Minimize jargon and make the importance of each impact clear.",
        "Avoid esoteric theory/K material unless explicitly requested.",
    ],
}
_LABELS = {
    JudgeCategory.TECH: r"(?:tech|technical)",
    JudgeCategory.FLOW: r"flow",
    JudgeCategory.FLAY: r"flay",
    JudgeCategory.FULLY_LAY: r"(?:fully[ _-]lay|lay)",
}


class JudgeAgent:
    def analyze(self, notes: str | None, *, category: JudgeCategory | None = None) -> JudgeProfile:
        profile = JudgeProfile(original_notes=notes)
        signals: dict[JudgeCategory, list[str]] = {}
        # Require a self-description or labeled category, not a stray keyword.
        # Negated statements do not match the affirmative prefix.
        for line in re.split(r"[\n.!?;]+", notes or ""):
            text = line.strip()
            for inferred, label in _LABELS.items():
                pattern = (
                    rf"^(?:i am|i'm)\s+(?:a\s+)?{label}\s+judge\b"
                    rf"|^(?:judge(?: category| type)?|category)\s*:\s*{label}\s*$"
                    rf"|^{label}\s*$"
                )
                if re.search(pattern, text, re.IGNORECASE):
                    signals.setdefault(inferred, []).append(text)
            # Preserve preference evidence as the complete original clause.
            if re.search(
                r"^(?:please )?(?:no spreading|do not spread|don't spread|slow down)\b", text, re.I
            ):
                profile.preferences.append(text)
                profile.guidance.append("Use a conversational pace and prioritize clarity.")
            conditional = bool(re.search(r"\b(?:unless|except|only if)\b", text, re.I))
            if conditional:
                profile.preferences.append(text)
                profile.warnings.append(
                    "Conditional preference preserved; no automatic exclusion applied."
                )
            if not conditional and re.search(
                r"^(?:please )?(?:no theory|do not run theory|don't run theory)\b", text, re.I
            ):
                profile.exclude_theory = True
                profile.preferences.append(text)
            if not conditional and re.search(
                r"^(?:please )?(?:no (?:kritiks|ks)|do not run (?:kritiks|ks)|"
                r"don't run (?:kritiks|ks))\b",
                text,
                re.I,
            ):
                profile.exclude_kritiks = True
                profile.preferences.append(text)
            if re.search(
                r"\b(?:prefer|want|value|prioritize)\b.*\b(?:examples|weighing|warrants|clarity)\b",
                text,
                re.I,
            ):
                profile.preferences.append(text)
        profile.matched_signals = [signal for values in signals.values() for signal in values]
        if category is not None:
            profile.category = category
            profile.classification_source = "explicit"
            if any(found != category for found in signals):
                profile.warnings.append(
                    "Explicit judge category overrides conflicting note labels."
                )
        elif len(signals) == 1:
            profile.category = next(iter(signals))
            profile.classification_source = "notes"
        else:
            profile.warnings.append(
                "Conflicting judge labels; select a category explicitly."
                if signals
                else "No clear judge label found; category remains unspecified."
            )
        # Specific preferences precede generic guidance. They are not replaced by it.
        profile.guidance.extend(
            _GUIDANCE.get(
                profile.category,
                ["Use clear warrants and weighing; no judge-specific assumptions applied."],
            )
        )
        profile.preferences = list(dict.fromkeys(profile.preferences))
        return profile
