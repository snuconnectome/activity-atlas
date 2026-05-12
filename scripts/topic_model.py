"""BERTopic + UMAP topic modeling for commit messages.

Reads:  data/raw/commits.json   (output of fetch_commits.py)
Writes: data/topics.json        (cluster definitions + metadata)
        data/embeddings.json    (per-commit 2D UMAP projection)

Strategy
--------
1. Preprocess: strip conventional-commit prefixes, drop merges, keep Korean
2. Embed with paraphrase-multilingual-MiniLM-L12-v2 (440MB, supports ko/en)
3. Cluster with BERTopic + HDBSCAN (min_cluster_size=5, min_samples=2)
4. If degenerate (unique_topics < 3 OR > 70% in -1), fall back to KMeans(k=6)
5. UMAP 2D projection (n_neighbors=10, min_dist=0.3) for the scatter page
6. Assign Okabe-Ito colors to non-outlier topics
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from bertopic import BERTopic
from bertopic.representation import KeyBERTInspired
from hdbscan import HDBSCAN
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import CountVectorizer
from umap import UMAP


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
COMMITS_IN = REPO / "data" / "raw" / "commits.json"
TOPICS_OUT = REPO / "data" / "topics.json"
EMBEDDINGS_OUT = REPO / "data" / "embeddings.json"

EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# Okabe-Ito color-blind safe palette (excluding black/yellow which are reserved)
OKABE_ITO = [
    "#0072B2",  # Neural Teal (blue)
    "#E69F00",  # Signal Orange
    "#009E73",  # Bluish green
    "#D55E00",  # Vermillion
    "#56B4E9",  # Sky blue
    "#CC79A7",  # Reddish purple
    "#F0E442",  # Yellow (less ideal but for 7th cluster)
    "#000000",  # Black (8th cluster only)
]
OUTLIER_COLOR = "#9E9E9E"  # Neutral gray for HDBSCAN's -1 outlier cluster

CONV_COMMIT_RE = re.compile(
    r"^(feat|fix|chore|docs|refactor|test|perf|style|build|ci|revert|wip)(\([^)]*\))?:\s*",
    re.IGNORECASE,
)
MERGE_RE = re.compile(r"^Merge ", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def preprocess_messages(commits: list[dict]) -> tuple[list[dict], list[str]]:
    """Return (filtered commits, cleaned message texts) aligned by index.

    - Drop merge commits
    - Strip conventional-commit prefixes from the first line only
    - Lowercase English tokens, leave Korean untouched
    - Keep first 2 lines (subject + first body para usually)
    """
    filtered: list[dict] = []
    texts: list[str] = []
    for c in commits:
        msg = c.get("message", "").strip()
        if not msg or MERGE_RE.match(msg):
            continue
        # Take subject + optional first body line for context
        lines = msg.splitlines()
        subject = CONV_COMMIT_RE.sub("", lines[0]).strip()
        body_extra = ""
        if len(lines) >= 3 and lines[1].strip() == "" and lines[2].strip():
            body_extra = " " + lines[2].strip()
        cleaned = (subject + body_extra).strip()
        if not cleaned:
            continue
        # Only lowercase ASCII letters — leave Korean (and other non-ASCII) intact
        cleaned = "".join(ch.lower() if ch.isascii() and ch.isalpha() else ch for ch in cleaned)
        filtered.append(c)
        texts.append(cleaned)
    return filtered, texts


def is_degenerate(topic_labels: list[int]) -> bool:
    """HDBSCAN degeneracy heuristics for low-N data."""
    if not topic_labels:
        return True
    unique = set(topic_labels) - {-1}
    if len(unique) < 3:
        return True
    n_outlier = sum(1 for t in topic_labels if t == -1)
    if n_outlier / len(topic_labels) > 0.70:
        return True
    return False


def cluster_primary(embeddings: np.ndarray, texts: list[str]) -> tuple[list[int], BERTopic]:
    """HDBSCAN-backed BERTopic. Returns (topic_labels, model)."""
    umap_model = UMAP(
        n_neighbors=10, min_dist=0.3, n_components=5,
        random_state=42, low_memory=False,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=5, min_samples=2,
        metric="euclidean", cluster_selection_method="eom",
        prediction_data=True,
    )
    vectorizer_model = CountVectorizer(
        ngram_range=(1, 2), min_df=1, stop_words=None,
    )
    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model,
        representation_model=KeyBERTInspired(),
        min_topic_size=5,
        calculate_probabilities=False,
        verbose=False,
    )
    topics, _ = topic_model.fit_transform(texts, embeddings)
    return list(topics), topic_model


def cluster_fallback(embeddings: np.ndarray, texts: list[str], k: int = 6) -> tuple[list[int], dict[int, list[str]]]:
    """KMeans fallback with KeyBERT-style keyword extraction per cluster."""
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(embeddings).tolist()

    # Extract keywords per cluster via simple TF-IDF
    from sklearn.feature_extraction.text import TfidfVectorizer
    tfidf = TfidfVectorizer(max_features=200, ngram_range=(1, 2))
    tfidf_matrix = tfidf.fit_transform(texts)
    vocab = tfidf.get_feature_names_out()
    keywords_per_cluster: dict[int, list[str]] = {}
    for cluster_id in range(k):
        mask = np.array([l == cluster_id for l in labels])
        if not mask.any():
            keywords_per_cluster[cluster_id] = []
            continue
        cluster_tfidf = np.asarray(tfidf_matrix[mask].mean(axis=0)).flatten()
        top_idx = cluster_tfidf.argsort()[-5:][::-1]
        keywords_per_cluster[cluster_id] = [vocab[i] for i in top_idx]
    return labels, keywords_per_cluster


def umap_2d(embeddings: np.ndarray) -> np.ndarray:
    """Project to 2D for visualization."""
    reducer = UMAP(n_neighbors=10, min_dist=0.3, n_components=2, random_state=42)
    return reducer.fit_transform(embeddings)


def assign_colors(topic_ids: list[int]) -> dict[int, str]:
    """Map topic_id to color. -1 → outlier gray, others → Okabe-Ito sequential."""
    palette = {}
    non_outlier = sorted(t for t in set(topic_ids) if t != -1)
    for i, t in enumerate(non_outlier):
        palette[t] = OKABE_ITO[i % len(OKABE_ITO)]
    if -1 in topic_ids:
        palette[-1] = OUTLIER_COLOR
    return palette


def build_topic_records(
    topic_ids: list[int],
    topic_model: BERTopic | None,
    fallback_keywords: dict[int, list[str]] | None,
) -> list[dict]:
    """Construct topics.json records."""
    palette = assign_colors(topic_ids)
    counts = {t: topic_ids.count(t) for t in set(topic_ids)}
    records: list[dict] = []
    for t in sorted(counts.keys()):
        if topic_model is not None:
            # BERTopic path
            words = [w for w, _ in topic_model.get_topic(t)[:5]] if t != -1 else []
            label = "outliers" if t == -1 else " / ".join(words[:3])
        else:
            # KMeans fallback path
            words = fallback_keywords.get(t, [])[:5] if fallback_keywords else []
            label = " / ".join(words[:3]) or f"cluster-{t}"
        records.append({
            "topic_id": int(t),
            "label": label,
            "top_words": list(words),
            "size": int(counts[t]),
            "color": palette[t],
        })
    return records


def main() -> int:
    if not COMMITS_IN.exists():
        print(f"ERROR: {COMMITS_IN} not found. Run fetch_commits.py first.", file=sys.stderr)
        return 1

    commits = json.loads(COMMITS_IN.read_text(encoding="utf-8"))
    print(f"Activity Atlas — topic modeling on {len(commits)} commits")

    filtered, texts = preprocess_messages(commits)
    print(f"  Preprocessed: {len(filtered)} non-merge commits with non-empty messages")

    print(f"  Loading embedding model: {EMBED_MODEL} ...")
    model = SentenceTransformer(EMBED_MODEL)
    embeddings = model.encode(texts, show_progress_bar=False)
    print(f"  Embedded → shape {embeddings.shape}")

    # Primary: BERTopic + HDBSCAN
    try:
        topics_primary, topic_model = cluster_primary(embeddings, texts)
        print(f"  HDBSCAN result: {len(set(topics_primary))} unique labels, {topics_primary.count(-1)} outliers")
    except Exception as exc:
        print(f"  HDBSCAN failed: {exc} — going straight to KMeans fallback")
        topics_primary = [-1] * len(texts)
        topic_model = None

    if topic_model is not None and not is_degenerate(topics_primary):
        topic_ids = topics_primary
        clustering_method = "hdbscan"
        fallback_keywords = None
    else:
        print("  ⚠️  HDBSCAN degenerate → switching to KMeans(k=6) fallback")
        topic_ids, fallback_keywords = cluster_fallback(embeddings, texts, k=6)
        clustering_method = "kmeans_fallback"
        topic_model = None  # Disable BERTopic path in record builder

    # UMAP 2D for scatter
    print("  UMAP 2D projection ...")
    coords = umap_2d(embeddings)

    # Build outputs
    topic_records = build_topic_records(topic_ids, topic_model, fallback_keywords)

    topics_doc = {
        "topics": topic_records,
        "metadata": {
            "clustering_method": clustering_method,
            "n_commits": len(filtered),
            "model": EMBED_MODEL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    TOPICS_OUT.write_text(
        json.dumps(topics_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    embedding_records = [
        {
            "sha": c["sha"],
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
            "topic_id": int(topic_ids[i]),
        }
        for i, c in enumerate(filtered)
    ]
    EMBEDDINGS_OUT.write_text(
        json.dumps(embedding_records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"✅ {clustering_method}: {len(topic_records)} clusters")
    for r in topic_records:
        print(f"    [{r['topic_id']:>2}] n={r['size']:>2}  {r['color']}  {r['label']}")
    print()
    print(f"   topics       → {TOPICS_OUT.relative_to(REPO)}")
    print(f"   embeddings   → {EMBEDDINGS_OUT.relative_to(REPO)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
