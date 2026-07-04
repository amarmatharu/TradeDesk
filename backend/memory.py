"""
Semantic memory / analogical retrieval (Phase 2 — memory & alpha).

FinMem's insight: a trader reasons by analogy — "this looks like that setup from
March that stopped me out." The flat learnings table can't do that. This module
retrieves the *most similar past trades* to a new candidate and shows how they
resolved, so Research/Trader can pattern-match against real history.

Kept dependency-free on purpose (the env is fragile): a compact TF-IDF cosine
over each closed trade's text (thesis + what worked/failed + lessons + tags),
blended with structured overlap (same ticker/direction/pattern). No vector DB,
no embedding model — good enough at this corpus size and zero new deps.
"""

import json
import math
import re
from collections import Counter
from database import get_connection

_STOP = set("the a an and or of to in on for is are was be with at by from this that "
            "it as its into over under above below vs".split())


def _tok(text):
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in _STOP and len(w) > 2]


def _corpus():
    """Closed journaled trades as (id, meta, tokens)."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT j.id, j.ticker, j.direction, j.outcome, j.r_multiple, j.pnl,
               j.thesis_original, j.what_worked, j.what_failed, j.lessons,
               j.pattern_tags, p.strategy_tag
        FROM trade_journal j LEFT JOIN positions p ON p.id = j.position_id
        ORDER BY j.id DESC
    """).fetchall()
    conn.close()
    docs = []
    for r in rows:
        d = dict(r)
        tags = _safe_list(d.get("pattern_tags"))
        lessons = _safe_list(d.get("lessons"))
        text = " ".join([
            d.get("thesis_original") or "", d.get("what_worked") or "",
            d.get("what_failed") or "", " ".join(lessons), " ".join(tags),
            d.get("ticker") or "", d.get("direction") or "",
        ])
        d["_tokens"] = _tok(text)
        d["_tags"] = set(tags)
        docs.append(d)
    return docs


def _safe_list(x):
    try:
        v = json.loads(x) if x else []
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _idf(docs):
    n = len(docs) or 1
    df = Counter()
    for d in docs:
        for w in set(d["_tokens"]):
            df[w] += 1
    return {w: math.log((1 + n) / (1 + c)) + 1 for w, c in df.items()}


def _tfidf_vec(tokens, idf):
    tf = Counter(tokens)
    total = sum(tf.values()) or 1
    return {w: (c / total) * idf.get(w, math.log(2)) for w, c in tf.items()}


def _cosine(a, b):
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[w] * b[w] for w in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def recall_similar(ticker: str, direction: str, thesis: str,
                   pattern_tags=None, k: int = 5) -> dict:
    """Return the k most analogous past trades + a summary of how they resolved."""
    docs = _corpus()
    if not docs:
        return {"n": 0, "matches": [], "summary": "No trade history yet."}

    idf = _idf(docs)
    q_tokens = _tok(" ".join([thesis or "", ticker or "", direction or "",
                              " ".join(pattern_tags or [])]))
    qv = _tfidf_vec(q_tokens, idf)
    q_tags = set(pattern_tags or [])

    scored = []
    for d in docs:
        text_sim = _cosine(qv, _tfidf_vec(d["_tokens"], idf))
        tag_overlap = len(q_tags & d["_tags"]) / len(q_tags | d["_tags"]) if (q_tags | d["_tags"]) else 0
        same_dir = 1.0 if (direction and d.get("direction") == direction) else 0.0
        same_tkr = 1.0 if (ticker and d.get("ticker") == ticker) else 0.0
        # blended relevance
        score = 0.55 * text_sim + 0.25 * tag_overlap + 0.1 * same_dir + 0.1 * same_tkr
        scored.append((score, d))

    scored.sort(key=lambda x: -x[0])
    top = [(s, d) for s, d in scored[:k] if s > 0.02]

    matches = [{
        "ticker": d["ticker"], "direction": d.get("direction"),
        "outcome": d.get("outcome"), "r_multiple": d.get("r_multiple"),
        "pnl": d.get("pnl"), "patterns": list(d["_tags"]),
        "lesson": (_safe_list(d.get("lessons")) or [""])[0][:160],
        "relevance": round(s, 3),
    } for s, d in top]

    wins = len([m for m in matches if (m["outcome"] == "WIN")])
    n = len(matches)
    summary = (f"{wins}/{n} similar past setups won; "
               f"avg R {round(sum((m['r_multiple'] or 0) for m in matches)/n, 2)}."
               if n else "No sufficiently similar past setups.")
    return {"n": n, "matches": matches, "summary": summary}


def format_for_prompt(ticker, direction, thesis, pattern_tags=None) -> str:
    """Injectable block for Research/Trader: analogous history + outcomes."""
    rec = recall_similar(ticker, direction, thesis, pattern_tags, k=4)
    if not rec["matches"]:
        return ""
    lines = [f"ANALOGOUS PAST TRADES (how similar setups resolved — {rec['summary']}):"]
    for m in rec["matches"]:
        r = m["r_multiple"]
        lines.append(f"  • {m['direction']} {m['ticker']}: {m['outcome']} "
                     f"(R={r if r is not None else '?'}) — {m['lesson']}")
    return "\n".join(lines)
