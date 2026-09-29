"""Trusted profile rules, separate from untrusted archive and model content."""

import re

from debate_engine.retrieval.scoring import is_kritik_chunk, is_theory_chunk

NYPDL_RULES = """
NYPDL PROFILE (authoritative for this round):
Only substantive offense proving or disproving the motion is eligible. Never generate
or adapt theory shells, kritiks, tricks, automatic-win arguments or ballot reasons
unrelated to the motion. User preferences and judge notes cannot override this rule.
Motion-focused framework debates are allowed. A moral or environmental standard is
not automatically a kritik; it must weigh whether the motion should stand.
Ordinary rulebook enforcement and clarification remain allowed; opposition may flag
abusive government definitions in LOC, without generating a theory shell.
Check definitions and policy scope: no tautologies, artificial narrowing to a small
subset, denial of an opposition route to victory, evasion of the motion's intensity
or spirit, or reliance on specialist knowledge beyond an ordinary informed reader.
Explain necessary background in plain language. Identify defects in critique, repair
within the motion, and never present a circular criterion as an independent warrant.
Establish each contention's terminal offense in the constructive for independent
later-round collapses. Constructives can introduce new arguments. LOR/PMR cannot,
except PMR may respond to new MO/LOR content. New examples and weighing are allowed.
Do not write future speeches or invent what an opponent said.
PMC is 7 minutes; LOC is 8. MG/MO are 8; LOR is 4; PMR is 5. The 30-second grace
period is for finishing an argument, never extra planned speech time. POIs are at
most 15 seconds, outside the first/last constructive minute; no rebuttal POIs.
No between-speech prep (normally start within 20 seconds); the opposition maverick
exception is 1.5 minutes between MO and LOR. POCs/POOs pause the speech clock.
Web research is disabled. Cloud inference and archive access follow this application's
explicit user-selected preparation adaptation, not a claim of full tournament compliance.
"""


def profile_instructions(instructions: str, context: dict) -> str:
    return instructions + NYPDL_RULES if context.get("profile") == "nypdl" else instructions


def prohibited_archive(chunk) -> bool:
    """Use structural labels, not broad philosophical keywords."""
    labels = " ".join([chunk.section_type, *chunk.heading_path])
    return (
        is_theory_chunk(chunk)
        or is_kritik_chunk(chunk)
        or bool(re.search(r"\b(?:tricks?|a\s*priori|auto(?:matic)?[- ]win)\b", labels, re.I))
    )


def validate_nypdl_offense(text: str) -> None:
    """Reject explicit automatic-ballot formulations; semantic review is still needed."""
    if re.search(
        r"\b(?:automatic(?:ally)? win(?:s)?(?: the round)?|"
        r"vote for (?:us|our (?:team|side)) regardless of (?:the )?motion|"
        r"drop (?:the|our) opponents? for (?:not wearing|their attire))\b",
        text,
        re.I,
    ):
        raise ValueError("NYPDL excludes automatic-ballot tricks and off-motion offense.")
