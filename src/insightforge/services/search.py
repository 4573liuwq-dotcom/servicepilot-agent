import hashlib

import httpx

from insightforge.domain import Evidence, SourceType


class WebSearch:
    def __init__(self, api_key: str | None, timeout: float = 20.0):
        self.api_key = api_key
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, limit: int = 3) -> list[Evidence]:
        if not self.api_key:
            return []
        response = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": self.api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": limit,
                "include_answer": False,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        evidence = []
        for item in response.json().get("results", []):
            digest = hashlib.sha256(item["url"].encode()).hexdigest()[:8]
            evidence.append(
                Evidence(
                    id=f"WEB-{digest}",
                    title=item.get("title", "Web result"),
                    content=item.get("content", "")[:5000],
                    source_type=SourceType.WEB,
                    url=item["url"],
                    score=max(0.0, min(1.0, float(item.get("score", 0.5)))),
                )
            )
        return evidence
