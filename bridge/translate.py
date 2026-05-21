from __future__ import annotations

import csv
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TRANSLATIONS_CSV = DATA_DIR / "danbooru_translations_jp.csv"

_TAG_JP_MAP: dict[str, str] | None = None
_DESC_START_RE = re.compile(
    r",\s+((?:A|An|The|This|In|She|He|It|There|We|They|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten)\s+[a-zA-Z].*)$"
)
_DESC_FAIL_NOTE = "（説明文の翻訳を取得できませんでした）"


def load_tag_jp_map() -> dict[str, str]:
    global _TAG_JP_MAP
    if _TAG_JP_MAP is not None:
        return _TAG_JP_MAP
    mapping: dict[str, str] = {}
    if TRANSLATIONS_CSV.exists():
        with TRANSLATIONS_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.reader(fh):
                if not row:
                    continue
                tag = (row[0] or "").strip()
                if not tag:
                    continue
                for value in row[1:]:
                    for part in str(value).split(","):
                        part = part.strip()
                        if part:
                            mapping.setdefault(tag, part)
                            break
                    if tag in mapping:
                        break
    _TAG_JP_MAP = mapping
    return _TAG_JP_MAP


def parse_tag_list(text: str) -> list[str]:
    tags: list[str] = []
    for part in re.split(r"[\n,]+", text or ""):
        token = part.strip()
        if token:
            tags.append(token)
    return tags


def split_prompt_parts(prompt: str) -> tuple[str, str]:
    prompt = (prompt or "").strip()
    if not prompt:
        return "", ""
    match = _DESC_START_RE.search(prompt)
    if match:
        return prompt[: match.start()].rstrip(", ").strip(), match.group(1).strip()
    parts = prompt.split("\n\n", 1)
    if len(parts) == 2:
        return parts[0].strip().rstrip(","), parts[1].strip()
    return prompt, ""


def lookup_tag_jp(jp_map: dict[str, str], tag: str) -> str:
    raw = (tag or "").strip()
    if not raw:
        return ""
    for key in (raw, raw.replace(" ", "_"), raw.replace("_", " ")):
        label = jp_map.get(key)
        if label:
            return label
    return ""


def _translate_google_unofficial(text: str, src: str = "en", dest: str = "ja") -> str:
    params = urllib.parse.urlencode({"client": "gtx", "sl": src, "tl": dest, "dt": "t", "q": text})
    url = f"https://translate.googleapis.com/translate_a/single?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    chunks = payload[0] if isinstance(payload, list) and payload else []
    parts = [str(chunk[0]).strip() for chunk in chunks if isinstance(chunk, (list, tuple)) and chunk and chunk[0]]
    translated = "".join(parts).strip()
    if not translated:
        raise RuntimeError("translation returned empty text")
    return translated


def translate_text_via_api(text: str, src: str = "en", dest: str = "ja") -> str:
    text = (text or "").strip()
    if not text:
        return ""
    return _translate_google_unofficial(text, src=src, dest=dest)


def translate_prompt(prompt: str, tags: list[str] | None = None, caption: str = "") -> str:
    prompt = (prompt or "").strip()
    caption = (caption or "").strip()
    if prompt:
        tag_part, desc_part = split_prompt_parts(prompt)
        if not tag_part:
            tag_part = prompt
            desc_part = caption or desc_part
        tag_tokens = parse_tag_list(tag_part)
        if not tag_tokens and tags:
            tag_tokens = [str(tag).strip() for tag in tags if str(tag).strip()]
    else:
        tag_tokens = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
        desc_part = caption
    jp_map = load_tag_jp_map()
    translated_tags: list[str] = []
    unknown_indexes: list[int] = []
    unknown_tags: list[str] = []
    for index, tag in enumerate(tag_tokens):
        label = lookup_tag_jp(jp_map, tag)
        if label:
            translated_tags.append(label)
        else:
            translated_tags.append(tag)
            unknown_indexes.append(index)
            unknown_tags.append(tag)
    for idx, tag in zip(unknown_indexes, unknown_tags):
        try:
            translated_tags[idx] = translate_text_via_api(tag.replace(" ", "_"))
        except Exception:
            pass
    tag_text = ", ".join(translated_tags)
    desc_failed = False
    desc_text = ""
    if desc_part:
        try:
            desc_text = translate_text_via_api(desc_part)
        except Exception:
            desc_failed = True
    lines: list[str] = []
    if tag_text:
        lines.append(tag_text)
    if desc_text:
        if lines:
            lines.append("")
        lines.append(desc_text)
    elif desc_failed:
        if lines:
            lines.append("")
        lines.append(_DESC_FAIL_NOTE)
    return "\n".join(lines)
