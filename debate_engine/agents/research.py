"""Permission-gated live search with bounded requests and traceable excerpts."""

import hashlib
import ipaddress
import json
import re
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from debate_engine.config import Settings, get_settings
from debate_engine.retrieval.queries import clean_motion
from debate_engine.schemas.adaptation import ResearchPacket, ResearchSource
from debate_engine.schemas.rounds import KnowledgePacket, RoundInput


class ResearchProvider(Protocol):
    def search(self, query: str, *, max_results: int) -> list[dict]: ...


class ResearchProviderError(RuntimeError):
    """Safe public error without provider response bodies or credentials."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TavilySearchProvider:
    """Minimal adapter to the documented Tavily search endpoint; no extra SDK."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings.research

    def search(self, query: str, *, max_results: int) -> list[dict]:
        key = self.settings.api_key
        if key is None or not key.get_secret_value().strip():
            raise ResearchProviderError("Research provider API key is not configured.")
        payload = {
            "query": query,
            "search_depth": "basic",
            "topic": "general",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_published_date": True,
        }
        request = Request(
            "https://api.tavily.com/search",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key.get_secret_value()}",
            },
            method="POST",
        )
        try:
            with build_opener(_NoRedirects()).open(
                request, timeout=self.settings.timeout_seconds
            ) as response:
                data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ResearchProviderError("Research response exceeded the size limit.")
            parsed = json.loads(data)
            results = parsed.get("results") if isinstance(parsed, dict) else None
            if not isinstance(results, list):
                raise ResearchProviderError("Research provider returned an invalid response.")
            return results[:max_results]
        except ResearchProviderError:
            raise
        except HTTPError as exc:
            raise ResearchProviderError(f"Research provider HTTP error {exc.code}.") from None
        except Exception:
            raise ResearchProviderError(
                "Research request failed; check connection and configuration."
            ) from None


def canonical_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Source URL must be text.")
    parts = urlsplit(value)
    if (
        parts.scheme not in {"https", "http"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise ValueError("Source URL must be a public web link.")
    host = parts.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("Local source URLs are not supported.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private source URLs are not supported.")
    if any(char.isspace() for char in value):
        raise ValueError("Invalid source URL.")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), "")
    )


def publication_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        try:
            return parsedate_to_datetime(value).date()
        except (TypeError, ValueError, OverflowError):
            return None


def research_queries(context: RoundInput, max_queries: int) -> list[str]:
    # Only public round terms are sent. Never include archive text or judge notes.
    topic = re.sub(r"\s+", " ", clean_motion(context.motion)).strip()[:500]
    year = context.current_year
    queries = [
        f"{topic} {year} official statistics government data",
        f"{topic} peer reviewed study evidence outcomes limitations",
    ]
    concepts = " ".join(context.explicit_concepts)[:300]
    queries.append(f"{topic} {concepts} {year} recent developments evidence risks".strip())
    return list(dict.fromkeys(queries))[:max_queries]


class ResearchAgent:
    def __init__(
        self, settings: Settings | None = None, *, provider: ResearchProvider | None = None
    ):
        self.settings = settings or get_settings()
        self.provider = provider

    def run(
        self, context: RoundInput, *, knowledge: KnowledgePacket | None = None
    ) -> ResearchPacket:
        # Check the round permission before touching a provider, even an injected one.
        if not context.prep_rules.internet_allowed:
            return ResearchPacket(status="disabled_by_prep_rules")
        config = self.settings.research
        queries = research_queries(context, config.max_queries)
        packet = ResearchPacket(status="no_results", queries=queries)
        if knowledge is not None:
            packet.verification_chunk_ids = [
                key for key, item in knowledge.items.items() if item.verification_notes
            ]
            packet.coverage_gaps = [category.value for category in knowledge.coverage_gaps]
        provider = self.provider
        if provider is None:
            if config.api_key is None or not config.api_key.get_secret_value().strip():
                packet.status = "missing_credentials"
                packet.warnings.append(
                    "Set DEBATE_ENGINE_RESEARCH__API_KEY to enable live research."
                )
                return packet
            provider = TavilySearchProvider(self.settings)
        sources: dict[str, ResearchSource] = {}
        failures = 0
        invalid = 0
        for query in queries:
            packet.queries_attempted += 1
            try:
                rows = provider.search(query, max_results=config.results_per_query)
                if not isinstance(rows, list):
                    raise ResearchProviderError("Invalid result list.")
                packet.queries_completed += 1
            except Exception:
                # Untrusted backend exceptions can contain credentials or raw response text.
                failures += 1
                packet.warnings.append(
                    f"Research query {packet.queries_attempted} failed; results may be incomplete."
                )
                continue
            for row in rows[: config.results_per_query]:
                try:
                    if not isinstance(row, dict):
                        raise ValueError("Invalid result")
                    url = canonical_url(row["url"])
                    title, excerpt = row["title"], row["content"]
                    if (
                        not isinstance(title, str)
                        or not isinstance(excerpt, str)
                        or not title.strip()
                        or not excerpt.strip()
                    ):
                        raise ValueError("Missing source text")
                    if url in sources:
                        if query not in sources[url].query_matches:
                            sources[url].query_matches.append(query)
                        continue
                    published = publication_date(row.get("published_date"))
                    notes = ["Search excerpt only; open the source and verify claims and context."]
                    if published is None:
                        notes.append("Publication date unavailable; do not assume this is current.")
                    elif published.year < context.current_year:
                        notes.append(
                            "Published before the round year; check current applicability."
                        )
                    elif published > datetime.now(UTC).date():
                        notes.append("Provider reports a future publication date; verify metadata.")
                    sources[url] = ResearchSource(
                        source_id=hashlib.sha256(url.encode()).hexdigest()[:16],
                        title=title[:500],
                        url=url,
                        excerpt=excerpt[: config.max_excerpt_characters],
                        published_date=published,
                        retrieved_at=datetime.now(UTC),
                        query_matches=[query],
                        notes=notes,
                    )
                except (KeyError, ValueError, TypeError):
                    invalid += 1
        packet.sources = list(sources.values())
        if failures == len(queries):
            packet.status = "failed"
        elif failures or invalid:
            packet.status = "partial"
        else:
            packet.status = "completed" if sources else "no_results"
        if invalid:
            packet.warnings.append(f"Skipped {invalid} malformed research results.")
        return packet
