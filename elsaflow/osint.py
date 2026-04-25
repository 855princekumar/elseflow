from __future__ import annotations

from statistics import mean
from urllib.parse import quote_plus

import requests

from elsaflow.models import OsintSignal, ResearchReport


class ShadowBrokerClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def fetch(self, category: str, topic: str) -> list[OsintSignal]:
        try:
            response = requests.get(
                f"{self.base_url}/api/osint/signals",
                params={"category": category, "topic": topic},
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("signals", [])
            signals = [
                OsintSignal(
                    source=item.get("source", "shadowbroker"),
                    title=item.get("title", "Untitled"),
                    summary=item.get("summary", ""),
                    url=item.get("url", ""),
                    sentiment_score=float(item.get("sentiment_score", 0.0)),
                    relevance_score=float(item.get("relevance_score", 0.0)),
                )
                for item in items
            ]
            if signals:
                return signals
        except Exception:
            pass

        combined_prompt = f"{category} {topic}".strip()
        collected: list[OsintSignal] = []
        collected.extend(fetch_gdelt_signals(topic or category))

        if any(word in combined_prompt.lower() for word in ["space", "satellite", "orbit"]):
            collected.extend(fetch_celestrak_signals())
            collected.extend(fetch_satnogs_signals())

        if any(word in combined_prompt.lower() for word in ["earth", "quake", "seismic", "volcano"]):
            collected.extend(fetch_usgs_signals())

        if collected:
            return collected[:12]
        return no_live_match_signals(category, topic)


def fetch_gdelt_signals(topic: str) -> list[OsintSignal]:
    try:
        response = requests.get(
            f"https://api.gdeltproject.org/api/v2/doc/doc?query={quote_plus(topic)}&mode=artlist&maxrecords=5&format=json",
            timeout=6,
        )
        response.raise_for_status()
        articles = response.json().get("articles", [])
        return [
            OsintSignal(
                source="gdelt",
                title=item.get("title", "Untitled GDELT article"),
                summary=item.get("seendate", "GDELT article match"),
                url=item.get("url", ""),
                sentiment_score=0.28 if idx % 2 == 0 else 0.12,
                relevance_score=0.75,
            )
            for idx, item in enumerate(articles[:5])
            if item.get("url")
        ]
    except Exception:
        return []


def fetch_celestrak_signals() -> list[OsintSignal]:
    try:
        response = requests.get(
            "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=json",
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        return [
            OsintSignal(
                source="celestrak",
                title=item.get("OBJECT_NAME", "Active satellite"),
                summary=f"NORAD {item.get('NORAD_CAT_ID', 'n/a')} from active orbital catalog",
                url="https://celestrak.org/NORAD/elements/",
                sentiment_score=0.05,
                relevance_score=0.67,
            )
            for item in payload[:5]
        ]
    except Exception:
        return []


def fetch_satnogs_signals() -> list[OsintSignal]:
    try:
        response = requests.get("https://db.satnogs.org/api/transmitters/?format=json", timeout=8)
        response.raise_for_status()
        payload = response.json()
        return [
            OsintSignal(
                source="satnogs",
                title=item.get("description", "SatNOGS transmitter"),
                summary=f"Alive={item.get('alive', 'unknown')} mode={item.get('mode', 'n/a')}",
                url=f"https://db.satnogs.org/transmitters/{item.get('id', '')}",
                sentiment_score=0.04,
                relevance_score=0.63,
            )
            for item in payload[:5]
        ]
    except Exception:
        return []


def fetch_usgs_signals() -> list[OsintSignal]:
    try:
        response = requests.get(
            "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&orderby=time&limit=5",
            timeout=6,
        )
        response.raise_for_status()
        features = response.json().get("features", [])
        return [
            OsintSignal(
                source="usgs",
                title=feature.get("properties", {}).get("title", "USGS event"),
                summary=f"Magnitude {feature.get('properties', {}).get('mag', 'n/a')}",
                url=feature.get("properties", {}).get("url", ""),
                sentiment_score=-0.22,
                relevance_score=0.66,
            )
            for feature in features[:5]
            if feature.get("properties", {}).get("url")
        ]
    except Exception:
        return []


def no_live_match_signals(category: str, topic: str) -> list[OsintSignal]:
    prompt = (topic or category).strip() or "requested topic"
    return [
        OsintSignal(
            source="no_live_match",
            title=f"No live ShadowBroker-compatible source matched: {prompt}",
            summary="This topic did not return enough real public-source matches from the current ShadowBroker-aligned feed set. No dummy placeholder articles were injected.",
            url="https://github.com/BigBodyCobain/Shadowbroker",
            sentiment_score=0.0,
            relevance_score=0.1,
        ),
    ]


def build_research_report(category: str, topic: str, signals: list[OsintSignal]) -> ResearchReport:
    sentiment_score = mean(signal.sentiment_score for signal in signals)
    confidence_score = mean(signal.relevance_score for signal in signals)

    edges = []
    if any(signal.source == "no_live_match" for signal in signals):
        edges.append("No ShadowBroker-compatible live source matched this topic")
    if sentiment_score > 0.4:
        edges.append("Positive consensus detected across public signals")
    if confidence_score > 0.75:
        edges.append("Signal quality is high enough for a small-risk trade")
    if sentiment_score < 0.15:
        edges.append("Asymmetric bearish setup detected")
    if not edges:
        edges.append("Signal strength is mixed; prefer caution")

    summary = (
        f"Collected {len(signals)} OSINT signals for {topic or category}. "
        f"Average sentiment {sentiment_score:.2f} with relevance {confidence_score:.2f}."
    )

    return ResearchReport(
        market_topic=topic,
        category=category,
        summary=summary,
        signals=signals,
        sentiment_score=sentiment_score,
        confidence_score=confidence_score,
        discovered_edges=edges,
    )
