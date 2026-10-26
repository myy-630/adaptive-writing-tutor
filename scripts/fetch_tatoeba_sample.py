"""Save a small attributed snapshot from Tatoeba's official read-only API."""

import json
import ssl
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import NAMESPACE_URL, uuid5

import certifi

QUERIES = ("school", "friend", "because", "yesterday", "although")
API_URL = "https://api.tatoeba.org/v1/sentences"
OUTPUT = Path("data/processed/tatoeba_sample.jsonl")
LICENSE = "CC BY 2.0 FR"


def fetch_query(query: str) -> list[dict]:
    parameters = urlencode(
        {
            "lang": "eng",
            "q": query,
            "license": LICENSE,
            "is_unapproved": "no",
            "is_orphan": "no",
            "word_count": "5-20",
            "sort": "created",
            "limit": 30,
            "showtrans": "none",
        }
    )
    context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(f"{API_URL}?{parameters}", timeout=30, context=context) as response:
        payload = json.load(response)
    return payload["data"]


def normalize(sentence: dict) -> dict | None:
    sentence_id = sentence["id"]
    text = sentence["text"].strip()
    owner = sentence.get("owner")
    if (
        sentence.get("license") != LICENSE
        or sentence.get("is_unapproved")
        or not owner
        or not text.isascii()
        or not 30 <= len(text) <= 180
    ):
        return None
    source = f"https://tatoeba.org/en/sentences/show/{sentence_id}"
    return {
        "id": str(uuid5(NAMESPACE_URL, source)),
        "content": text,
        "resource_type": "basic_sentence",
        "grade": None,
        "genre": None,
        "knowledge_node_ids": [],
        "ability_dimensions": [],
        "difficulty": None,
        "language_level": None,
        "source": source,
        "dataset_id": f"tatoeba:sentence:{sentence_id}",
        "license": LICENSE,
        "attribution": f"Tatoeba sentence #{sentence_id} by {owner}",
        "origin": "public",
        "processing_notes": (
            "Official API; English; approved; named author; 5–20 words; ASCII; unmodified text"
        ),
    }


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"Snapshot already exists: {OUTPUT}")
    sentences: dict[str, dict] = {}
    for query in QUERIES:
        for sentence in fetch_query(query):
            resource = normalize(sentence)
            if resource is not None:
                sentences[resource["dataset_id"]] = resource
    if len(sentences) < 30:
        raise RuntimeError(f"Only {len(sentences)} licensed sentences passed validation")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "".join(
            json.dumps(sentences[key], ensure_ascii=False, sort_keys=True) + "\n"
            for key in sorted(sentences)
        ),
        encoding="utf-8",
    )
    print(f"Saved {len(sentences)} licensed sentences to {OUTPUT}")


if __name__ == "__main__":
    main()
