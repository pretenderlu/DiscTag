from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from pypinyin import lazy_pinyin
from zhconv import convert

from . import encyclopedia as _encyc


CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


@dataclass(frozen=True)
class ResolvedQuery:
    album: str
    artist: str
    message: str = ""


def has_cjk(value: str) -> bool:
    return bool(value and CJK_RE.search(value))


def simplified(value: str) -> str:
    return convert(value or "", "zh-cn")


def resolve_chinese_query(album: str, artist: str, simplify: bool = True) -> ResolvedQuery:
    album = album.strip()
    artist = artist.strip()
    if not artist or (has_cjk(album) and has_cjk(artist)):
        return ResolvedQuery(simplified(album) if simplify else album, simplified(artist) if simplify else artist)
    candidates = _encyc.find_artist_candidates(artist)
    if not candidates:
        return ResolvedQuery(simplified(album) if simplify else album, simplified(artist) if simplify else artist)
    resolved_artist = candidates[0]["cn_name"]
    if has_cjk(album):
        return ResolvedQuery(simplified(album) if simplify else album, simplified(resolved_artist) if simplify else resolved_artist)
    best = None
    for candidate in candidates:
        for entry in _encyc.artist_albums(candidate):
            names = [entry.get("name") or "", entry.get("cn_name") or "", *(entry.get("aliases") or [])]
            names = [name for name in names if name]
            for name in names:
                score = name_match_score(album, name)
                if best is None or score > best[2]:
                    chinese_name = entry.get("cn_name") or next((item for item in names if has_cjk(item)), None)
                    if chinese_name:
                        best = (candidate, entry, score, chinese_name)
    if best and best[2] >= 0.55:
        source = "MusicBrainz" if best[0]["source"] == "mb" else "Wikidata"
        resolved_album = best[1]["cn_name"] or best[3]
        if simplify:
            resolved_album = simplified(resolved_album)
            resolved_artist = simplified(best[0]["cn_name"])
        else:
            resolved_artist = best[0]["cn_name"]
        return ResolvedQuery(resolved_album, resolved_artist, f"已通过 {source} 解析为 {resolved_artist}《{resolved_album}》")
    if simplify:
        resolved_artist = simplified(resolved_artist)
    return ResolvedQuery(simplified(album) if simplify else album, resolved_artist)


def name_match_score(user_query: str, candidate_name: str) -> float:
    if not user_query or not candidate_name:
        return 0.0
    user_norm = _normalize_text(user_query)
    candidate_norm = _normalize_text(candidate_name)
    candidate_pinyin = _to_pinyin(candidate_name)
    if user_norm and candidate_pinyin:
        if user_norm == candidate_pinyin:
            return 1.0
        if user_norm in candidate_pinyin or candidate_pinyin in user_norm:
            return 0.92
    if user_norm and candidate_norm:
        if user_norm == candidate_norm:
            return 1.0
        if user_norm in candidate_norm or candidate_norm in user_norm:
            return 0.85
    if user_norm and candidate_pinyin:
        return SequenceMatcher(None, user_norm, candidate_pinyin).ratio()
    return 0.0


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _to_pinyin(value: str) -> str:
    if not value:
        return ""
    try:
        return _normalize_text(" ".join(lazy_pinyin(value)))
    except Exception:
        return ""
