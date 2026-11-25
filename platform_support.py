"""Platform identification and share-link normalization (no network requests)."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


PLATFORMS = {
    "youtube": {"label": "YouTube", "domains": ("youtube.com", "youtu.be"), "cookie_domain": ".youtube.com"},
    "x": {"label": "X（Twitter）", "domains": ("x.com", "twitter.com"), "cookie_domain": ".x.com"},
    "instagram": {"label": "Instagram", "domains": ("instagram.com", "instagr.am"), "cookie_domain": ".instagram.com"},
    "bilibili": {"label": "B站", "domains": ("bilibili.com", "b23.tv"), "cookie_domain": ".bilibili.com"},
    "douyin": {"label": "抖音", "domains": ("douyin.com", "iesdouyin.com"), "cookie_domain": ".douyin.com"},
    "xiaohongshu": {"label": "小红书", "domains": ("xiaohongshu.com", "xhslink.com"), "cookie_domain": ".xiaohongshu.com"},
}
URL_PATTERN = re.compile(r"https?://[^\s<>\u3000，。！？；）】》」“”]+", re.IGNORECASE)

# Only characteristic names are used; sessionid, token and csrftoken occur on
# unrelated sites and must never choose a platform on their own.
COOKIE_NAME_HINTS = {
    "youtube": {"login_info", "ysc", "visitor_info1_live", "visitor_privacy_metadata"},
    "x": {"ct0", "twid"},
    "instagram": {"ds_user_id", "ig_did", "ig_nrcb"},
    "bilibili": {"sessdata", "bili_jct", "dedeuserid", "buvid3", "buvid4"},
    "douyin": {"ttwid", "odin_tt", "s_v_web_id"},
    "xiaohongshu": {"web_session", "websectiga", "xsecappid"},
}


def detect_cookie_platform(cookie_text: str, url: str = "") -> dict:
    """Local inference only. Never include cookie values in the result."""
    if not isinstance(cookie_text, str):
        raise ValueError("Cookie 必须是文本。")
    text = cookie_text.lstrip("\ufeff").strip(" \r\n")
    candidates = set()
    source = "unknown"
    if "\t" in text or text.startswith("#"):
        source = "domain"
        for line in text.splitlines():
            if line.startswith("#") and not line.startswith("#HttpOnly_"):
                continue
            fields = line.removeprefix("#HttpOnly_").split("\t")
            if len(fields) != 7:
                continue
            host = fields[0].lstrip(".").lower()
            for key, platform in PLATFORMS.items():
                domain = platform["cookie_domain"].lstrip(".")
                domains = (domain, "twitter.com") if key == "x" else (domain,)
                if any(host == item or host.endswith("." + item) for item in domains):
                    candidates.add(key)
    elif text:
        source = "cookie_names"
        raw = text.split(":", 1)[1].strip() if text.lower().startswith("cookie:") else text
        names = {part.split("=", 1)[0].strip().lower() for part in raw.split(";") if "=" in part}
        for key, hints in COOKIE_NAME_HINTS.items():
            if names & hints:
                candidates.add(key)
        if {"a1", "webid"} <= names:
            candidates.add("xiaohongshu")
    link_platform = infer_platform_key(extract_first_url(url)) if isinstance(url, str) and url.strip() else None
    ordered = [key for key in PLATFORMS if key in candidates]
    if len(candidates) == 1:
        platform = ordered[0]
    elif link_platform and (not candidates or link_platform in candidates):
        platform = link_platform
        source = "url"
    else:
        platform = None
        source = "ambiguous" if candidates else "unknown"
    return {"platform": platform, "candidates": ordered, "source": source}


def extract_first_url(raw_text: str) -> str:
    if not isinstance(raw_text, str):
        raise ValueError("视频链接必须是文本。")
    text = raw_text.strip()
    match = URL_PATTERN.search(text)
    return match.group(0).rstrip(").,?!\"'，。！？；;）】》」\u200b") if match else text


def infer_platform_key(url: str) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or parsed.username or parsed.password:
            return None
        host = (parsed.hostname or "").lower()
        if parsed.port not in (None, 80, 443):
            return None
    except ValueError:
        return None
    for key, platform in PLATFORMS.items():
        if any(host == domain or host.endswith("." + domain) for domain in platform["domains"]):
            return key
    return None


def normalize_supported_url(url: str) -> str:
    parsed = urlparse(url)
    platform = infer_platform_key(url)
    host = (parsed.hostname or "").lower()
    query = parse_qs(parsed.query)
    if platform == "youtube":
        if host == "youtu.be" or host.endswith(".youtu.be"):
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        if query.get("v"):
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/watch", "", urlencode({"v": query["v"][0]}), ""))
    if platform == "douyin":
        match = re.search(r"/(?:share/)?video/(\d+)", parsed.path)
        video_id = match.group(1) if match else (query.get("modal_id") or query.get("aweme_id") or [""])[0]
        if video_id.isdigit():
            return f"https://www.douyin.com/video/{video_id}"
    if platform == "xiaohongshu" and (host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com")):
        match = re.fullmatch(r"/(?:explore|discovery/item)/([\da-fA-F]+)/?", parsed.path)
        if match:
            # Signed share URLs must retain xsec_token and xsec_source verbatim.
            return urlunparse(("https", "www.xiaohongshu.com", f"/explore/{match.group(1).lower()}", "", parsed.query, ""))
    return url


def validate_url(raw_url: str) -> str:
    url = extract_first_url(raw_url)
    if not url:
        raise ValueError("请先输入视频链接。")
    if infer_platform_key(url) is None:
        raise ValueError("目前支持 YouTube、X（Twitter）、Instagram、B站、抖音和小红书链接。")
    return normalize_supported_url(url)
