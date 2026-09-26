"""Bounded retrieval of official reference material; never follow model URLs."""

from functools import lru_cache
from time import time
import httpx

SOURCES = [
    (
        "SAP AI-enabled integrations CodeJam",
        "https://raw.githubusercontent.com/SAP-samples/ai-enabled-integrations-codejam/main/README.md",
    ),
    (
        "SAP code-based agents CodeJam",
        "https://raw.githubusercontent.com/SAP-samples/codejam-code-based-agents/main/README.md",
    ),
]


ADAPTER_SOURCES = {
    'odata': ('SAP OData V2 receiver configuration', 'https://raw.githubusercontent.com/SAP-docs/btp-integration-suite/main/docs/ISuite_Integrations_APIs/configure-the-odata-v2-receiver-adapter-c5c2e38.md'),
    'soap': ('SAP SOAP receiver configuration', 'https://raw.githubusercontent.com/SAP-docs/btp-integration-suite/main/docs/ISuite_Integrations_APIs/configure-the-soap-soap-1-x-receiver-adapter-57f7b34.md'),
    'http': ('SAP CodeJam HTTP Request Reply example', 'https://raw.githubusercontent.com/SAP-samples/connecting-systems-services-integration-suite-codejam/main/exercises/03-build-first-integration-flow/README.md'),
}


@lru_cache(maxsize=32)
def _retrieve(hour, topics=()):
    results = []
    for title, url in [*(ADAPTER_SOURCES[key] for key in topics), *SOURCES]:
        row = {"title": title, "url": url, "status": "unavailable", "excerpt": ""}
        try:
            with httpx.stream("GET", url, timeout=3, follow_redirects=False) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) >= 12000:
                        break
                row.update(
                    status="retrieved", excerpt=bytes(content[:12000]).decode("utf-8", errors="replace")
                )
        except httpx.HTTPError:
            pass
        results.append(row)
    return results


def research_references(query):
    from .designer import references

    # Rank reviewed pattern guidance for the description, then attach live provenance.
    # This is a bounded official-source lookup, not a mirror of the Discover catalog.
    topics = tuple(key for key in ADAPTER_SOURCES if key in query.lower())
    return [*references(query), *_retrieve(int(time() // 3600), topics)]
