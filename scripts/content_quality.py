#!/usr/bin/env python3
"""
Content quality deterministic checker for a single page.

Why it matters (verified May 2026):
  - Flesch Reading Ease isn't a direct ranking factor (John Mueller, Yoast
    19.3 deprioritised it), but it's a useful proxy for accessibility.
  - Sentence and paragraph length affect skim-ability — and Google's
    Helpful Content System (merged into core ranking March 2024) now
    rewards content that's easy to consume.
  - Keyword stuffing: 5%+ density is a known spam signal.
  - AI-generated markers (Sept 2025 QRG update): Google's raters formally
    flag content that *looks* AI-written without E-E-A-T signals as low
    quality.
  - Passage-extractability: AI Overviews / ChatGPT cite passages of
    134-167 words (Ahrefs study). Pages should have well-bounded answer
    blocks of that length.

Checks reported:
  - Word count vs page-type minimum (homepage 500, service 800, blog 1500)
  - Flesch Reading Ease score (target: 60-70 for general audience)
  - Average sentence length (target: 15-20 words)
  - Average paragraph length (target: 2-4 sentences)
  - Keyword density: top 10 noun-like tokens, flagged at >5%
  - AI-generation markers heuristic: repetitive structures, formulaic
    phrases, lack of specifics
  - Passage extraction: identifies 134-167 word self-contained blocks
    suitable for AI citation
  - Author/byline presence (E-E-A-T)
  - Date stamps (publication / last updated)

Exit code:
  0 = quality OK, no major findings
  1 = fetch failed
  2 = quality issues (low word count, poor readability, stuffing, etc.)

Usage:
  content_quality.py <url> [--target-keyword "<phrase>"] [--page-type blog|service|home]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter

import requests
from bs4 import BeautifulSoup

from _fetch import fetch


_PAGE_TYPE_MIN_WORDS = {
    "home": 500, "service": 800, "blog": 1500,
    "product": 300, "category": 400, "location": 600, "landing": 600,
    "about": 400, "faq": 800,
}

# AI-generation markers (heuristic). Each occurrence: weak signal; multiple co-occurring: strong.
_AI_MARKERS = [
    r"\bin today's (?:fast-paced |digital |modern )?(?:world|era|age)\b",
    r"\bin (?:the |an? |today's )?(?:ever[\s-]?(?:changing|evolving))\b",
    r"\bplays a (?:crucial|vital|pivotal|significant|important) role\b",
    r"\bat the end of the day\b",
    r"\bit's (?:important|essential|crucial) to note that\b",
    r"\bdelve into\b", r"\bdive deep into\b", r"\bunlock the (?:secrets|potential)\b",
    r"\bnavigate the (?:complexities|landscape|world) of\b",
    r"\bstreamline (?:your|the) (?:workflow|process)\b",
    r"\bharness the power of\b", r"\bcutting[\s-]?edge\b",
    r"\brevolutionize (?:the |your )\w+\b",
    r"\bin conclusion,\s", r"\bto sum up,\s",
]

_AI_MARKER_RE = [re.compile(p, re.IGNORECASE) for p in _AI_MARKERS]


def _strip_chrome(soup: BeautifulSoup) -> str:
    """Remove nav/footer/header/script/style — return main visible text."""
    for el in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        el.decompose()
    # Prefer <main> or <article> if present
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return main.get_text(separator=" ", strip=True)


def _flesch_reading_ease(words: list[str], sentences: int) -> float:
    """Standard Flesch formula (English). Higher = easier."""
    if not words or sentences == 0:
        return 0.0
    # Approximate syllables by vowel groups
    def _syllables(w: str) -> int:
        w = w.lower()
        vowels = "aeiouy"
        count = 0
        prev_was_vowel = False
        for ch in w:
            is_vowel = ch in vowels
            if is_vowel and not prev_was_vowel:
                count += 1
            prev_was_vowel = is_vowel
        if w.endswith("e") and count > 1:
            count -= 1
        return max(1, count)

    total_syllables = sum(_syllables(w) for w in words)
    asl = len(words) / sentences           # avg sentence length
    asw = total_syllables / len(words)     # avg syllables per word
    return round(206.835 - 1.015 * asl - 84.6 * asw, 1)


def _find_paragraphs(soup: BeautifulSoup) -> list[str]:
    return [p.get_text(strip=True) for p in soup.find_all("p")
            if p.get_text(strip=True)]


def _sentences(text: str) -> list[str]:
    # Simple regex-based sentence split (good enough for English content)
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]


def _keyword_density(words: list[str], top_n: int = 10) -> list[dict]:
    """Top N most-frequent non-stopword tokens. Filters tokens < 4 chars."""
    stopwords = {
        "the", "and", "for", "are", "but", "not", "you", "with", "from", "this",
        "that", "have", "has", "was", "were", "will", "would", "can", "could",
        "all", "any", "your", "their", "they", "them", "our", "out", "what",
        "when", "where", "which", "who", "how", "more", "most", "other", "some",
        "such", "than", "into", "about", "also", "very", "just", "only", "yes",
        "much", "well", "make", "made", "many", "even",
    }
    filtered = [w.lower() for w in words if len(w) >= 4 and w.lower() not in stopwords]
    total = len(filtered) or 1
    counter = Counter(filtered)
    out = []
    for token, count in counter.most_common(top_n):
        pct = 100 * count / total
        flag = "stuffing" if pct > 5 else None
        out.append({"token": token, "count": count, "density_pct": round(pct, 2), "flag": flag})
    return out


def _extract_passages(soup: BeautifulSoup, min_w: int = 134, max_w: int = 200) -> list[dict]:
    """Find paragraphs in the 134-200 word range (optimal for AI citation)."""
    passages = []
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        wc = len(re.findall(r"\b\w+\b", text))
        if min_w <= wc <= max_w:
            passages.append({"word_count": wc, "excerpt": text[:160] + ("..." if len(text) > 160 else "")})
    return passages


def _ai_marker_hits(text: str) -> list[dict]:
    hits = []
    for pattern, regex in zip(_AI_MARKERS, _AI_MARKER_RE):
        matches = regex.findall(text)
        if matches:
            hits.append({"pattern": pattern, "count": len(matches)})
    return hits


def _detect_byline(soup: BeautifulSoup) -> str | None:
    # JSON-LD author
    for script in soup.find_all("script", type=re.compile(r"application/ld\+json", re.I)):
        try:
            data = json.loads(script.string or script.get_text() or "")
            if isinstance(data, dict):
                a = data.get("author")
                if isinstance(a, dict) and a.get("name"):
                    return a["name"]
                if isinstance(a, list) and a and isinstance(a[0], dict) and a[0].get("name"):
                    return a[0]["name"]
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        a = item.get("author")
                        if isinstance(a, dict) and a.get("name"):
                            return a["name"]
        except (json.JSONDecodeError, TypeError):
            pass
    # rel="author" link
    a = soup.find("a", rel="author")
    if a and a.get_text(strip=True):
        return a.get_text(strip=True)
    # Common byline classes
    for sel in [".byline", ".author", "[itemprop='author']"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return None


def _detect_dates(soup: BeautifulSoup) -> dict:
    return {
        "published_meta": (soup.find("meta", property="article:published_time") or {}).get("content") if soup.find("meta", property="article:published_time") else None,
        "modified_meta":  (soup.find("meta", property="article:modified_time") or {}).get("content") if soup.find("meta", property="article:modified_time") else None,
        "time_published": soup.find("time", attrs={"datetime": True})["datetime"] if soup.find("time", attrs={"datetime": True}) else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("--target-keyword", default=None,
                    help="primary keyword to check density for")
    ap.add_argument("--page-type", choices=list(_PAGE_TYPE_MIN_WORDS),
                    default="blog",
                    help="page type for word-count baseline (default: blog)")
    args = ap.parse_args()

    url = args.url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        r = fetch(url, timeout=15)
    except requests.RequestException as e:
        print(json.dumps({"url": url, "error": str(e)}, indent=2))
        return 1

    try:
        soup = BeautifulSoup(r.text, "lxml")
    except Exception:
        soup = BeautifulSoup(r.text, "html.parser")

    text = _strip_chrome(soup)
    words = re.findall(r"\b\w+\b", text)
    sentences = _sentences(text)
    paragraphs = _find_paragraphs(soup)

    word_count = len(words)
    sent_count = len(sentences)
    paragraph_lens_sentences = [len(_sentences(p)) for p in paragraphs] if paragraphs else []
    avg_sent_len = round(word_count / max(1, sent_count), 1)
    avg_para_len = round(sum(paragraph_lens_sentences) / max(1, len(paragraph_lens_sentences)), 1) if paragraph_lens_sentences else 0
    flesch = _flesch_reading_ease(words, sent_count)
    density = _keyword_density(words)
    passages = _extract_passages(soup)
    ai_markers = _ai_marker_hits(text)
    byline = _detect_byline(soup)
    dates = _detect_dates(soup)

    # Target keyword density (if provided)
    target_kw_density = None
    if args.target_keyword:
        kw_lower = args.target_keyword.lower()
        # Count occurrences as substring across full text (more accurate than tokenisation)
        kw_count = text.lower().count(kw_lower)
        target_kw_density = {
            "keyword": args.target_keyword,
            "count": kw_count,
            "density_pct": round(100 * kw_count * len(args.target_keyword.split()) / max(1, word_count), 2),
        }

    min_words = _PAGE_TYPE_MIN_WORDS[args.page_type]
    issues = []
    if word_count < min_words:
        issues.append(f"word count {word_count} below {args.page_type} baseline {min_words}")
    if word_count > 0 and sent_count > 0 and avg_sent_len > 30:
        issues.append(f"avg sentence length {avg_sent_len} words — target 15-20")
    if avg_para_len > 6:
        issues.append(f"avg paragraph {avg_para_len} sentences — target 2-4 for scannability")
    if flesch and flesch < 30:
        issues.append(f"Flesch {flesch} — very hard to read; target 60-70 for general audience")
    stuffed = [d for d in density if d["flag"] == "stuffing"]
    if stuffed:
        issues.append(f"{len(stuffed)} terms at >5% density — keyword stuffing risk")
    if len(ai_markers) >= 3:
        issues.append(f"{len(ai_markers)} AI-generation marker phrases detected (low E-E-A-T signal)")
    if not byline:
        issues.append("no author/byline detected — E-E-A-T weak")
    if not any(dates.values()):
        issues.append("no publish/update date detected — freshness signal missing")
    if word_count > 800 and not passages:
        issues.append("no 134-200 word self-contained passages — poor AI citation fit")

    out = {
        "url": url,
        "page_type": args.page_type,
        "word_count": word_count,
        "min_word_target": min_words,
        "sentence_count": sent_count,
        "avg_sentence_length_words": avg_sent_len,
        "paragraph_count": len(paragraphs),
        "avg_paragraph_length_sentences": avg_para_len,
        "flesch_reading_ease": flesch,
        "keyword_density_top10": density,
        "target_keyword_density": target_kw_density,
        "ai_generation_markers": ai_markers,
        "ai_generation_marker_count": len(ai_markers),
        "author_byline": byline,
        "dates": dates,
        "citable_passages_count": len(passages),
        "citable_passages": passages[:5],
        "issues": issues,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
