"""Internet search that builds fresh context for the agent.

Uses ``ddgs`` (DuckDuckGo, no API key) when installed. Finance-flavoured
query expansion turns a research topic into several targeted searches, and
results are rendered as markdown context the agent can cite.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str

    def to_markdown(self) -> str:
        return f"- **{self.title}**\n  {self.snippet}\n  {self.url}"


class WebSearch:
    def __init__(self, max_results: int = 6, region: str = "us-en") -> None:
        self.max_results = max_results
        self.region = region

    @property
    def available(self) -> bool:
        try:
            import ddgs  # noqa: F401  # type: ignore
            return True
        except ImportError:
            return False

    def search(self, query: str, max_results: int | None = None) -> list[SearchHit]:
        try:
            from ddgs import DDGS  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "ddgs is not installed. Install it with: pip install 'finagent[search]'"
            ) from exc
        hits: list[SearchHit] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, region=self.region, max_results=max_results or self.max_results):
                hits.append(
                    SearchHit(
                        title=r.get("title", ""),
                        url=r.get("href", ""),
                        snippet=r.get("body", ""),
                    )
                )
        return hits

    def finance_search(self, topic: str, query_templates: list[str] | None = None) -> list[SearchHit]:
        """Run several finance-flavoured queries and merge the hits."""
        templates = query_templates or [
            "{topic} latest news",
            "{topic} earnings results",
            "{topic} analyst outlook",
        ]
        seen: set[str] = set()
        merged: list[SearchHit] = []
        per_query = max(2, self.max_results // len(templates))
        for template in templates:
            try:
                for hit in self.search(template.format(topic=topic), max_results=per_query):
                    if hit.url and hit.url not in seen:
                        seen.add(hit.url)
                        merged.append(hit)
            except Exception:  # noqa: BLE001 - one failing query shouldn't kill research
                continue
        return merged[: self.max_results]

    @staticmethod
    def to_context(hits: list[SearchHit], heading: str = "Web search context") -> str:
        if not hits:
            return ""
        lines = [f"## {heading}", f"({len(hits)} results, fetched just now)"]
        lines.extend(h.to_markdown() for h in hits)
        return "\n".join(lines)
