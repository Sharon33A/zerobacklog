"""Secure public-link validation, classification, and metadata extraction."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import (
    parse_qs,
    parse_qsl,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

import httpx

from app.services.errors import ResourceActionError, UrlValidationError
from app.services.readiness import is_coding_relevant, summarize_text

SUPPORTED_SCHEMES = {"http", "https"}
REDIRECT_CODES = {301, 302, 303, 307, 308}
LINK_PATTERN = re.compile(r"https?://[^\s<>()\"']+")
ISO_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)
CODING_HOSTS = {
    "leetcode.com",
    "www.leetcode.com",
    "geeksforgeeks.org",
    "www.geeksforgeeks.org",
    "hackerrank.com",
    "www.hackerrank.com",
    "codeforces.com",
    "www.codeforces.com",
    "neetcode.io",
    "www.neetcode.io",
}
DOCUMENTATION_HOSTS = {
    "developer.mozilla.org",
    "docs.python.org",
    "docs.oracle.com",
    "learn.microsoft.com",
    "cplusplus.com",
    "en.cppreference.com",
}


@dataclass(frozen=True)
class ValidatedLink:
    original_url: str
    normalized_url: str
    hostname: str
    source_type: str


@dataclass(frozen=True)
class LinkSnapshot:
    title: str
    description: str | None
    author: str | None
    duration_seconds: int | None
    outbound_links: tuple[str, ...]
    text: str
    status: str
    explanation: str
    technical_reason: str
    confidence: float | None
    summary: str | None


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description: str | None = None
        self.author: str | None = None
        self.text_parts: list[str] = []
        self.headings: list[str] = []
        self._in_title = False
        self._ignored_depth = 0
        self._heading_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {key.lower(): value for key, value in attrs if value}
        if tag in {"script", "style", "svg", "noscript", "nav", "footer"}:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"h1", "h2", "h3"}:
            self._heading_depth += 1
        if tag == "meta":
            name = (
                attributes.get("name")
                or attributes.get("property")
                or ""
            ).lower()
            content = attributes.get("content", "").strip()
            if name in {"description", "og:description"} and content:
                self.description = self.description or content
            if name in {"author", "article:author"} and content:
                self.author = self.author or content

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript", "nav", "footer"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        if tag == "title":
            self._in_title = False
        if tag in {"h1", "h2", "h3"}:
            self._heading_depth = max(0, self._heading_depth - 1)

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._in_title:
            self.title = f"{self.title} {cleaned}".strip()
        if self._ignored_depth:
            return
        if self._heading_depth:
            self.headings.append(cleaned)
            self.text_parts.append(f"\n## {cleaned}\n")
        else:
            self.text_parts.append(cleaned)


def validate_link(url: str) -> ValidatedLink:
    value = url.strip()
    if not value or len(value) > 2048:
        raise UrlValidationError(
            "invalid_url",
            "Enter a valid public URL no longer than 2,048 characters.",
        )
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in SUPPORTED_SCHEMES or not parsed.hostname:
        raise UrlValidationError(
            "invalid_url",
            "Links must use http:// or https:// and include a hostname.",
        )
    if parsed.username or parsed.password:
        raise UrlValidationError(
            "unsafe_url",
            "Links containing embedded credentials are not supported.",
        )
    try:
        port = parsed.port
    except ValueError as exception:
        raise UrlValidationError("invalid_url", "The URL port is invalid.") from exception
    if port not in {None, 80, 443}:
        raise UrlValidationError(
            "unsafe_url",
            "Only standard public web ports are supported.",
        )

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".local"):
        raise UrlValidationError(
            "unsafe_url",
            "Local and private network links are not supported.",
        )
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise UrlValidationError(
            "unsafe_url",
            "Local and private network links are not supported.",
        )

    netloc = hostname
    if port and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    path = parsed.path or "/"
    normalized_query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    normalized = urlunsplit(
        (parsed.scheme.lower(), netloc, path, normalized_query, "")
    )
    return ValidatedLink(
        original_url=value,
        normalized_url=normalized,
        hostname=hostname,
        source_type=classify_source(hostname, path),
    )


def classify_source(hostname: str, path: str) -> str:
    host = hostname.lower()
    lowered_path = path.lower()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        return "youtube"
    if host in {"github.com", "www.github.com"}:
        return "github_repository"
    if any(
        marker in lowered_path
        for marker in ("sheet", "roadmap", "practice-list", "problem-list")
    ):
        return "coding_sheet"
    if host in CODING_HOSTS:
        return "coding_platform"
    if host in DOCUMENTATION_HOSTS or host.startswith("docs."):
        return "documentation"
    return "website"


def assert_public_hostname(hostname: str, port: int = 443) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exception:
        raise UrlValidationError(
            "link_inaccessible",
            "The link hostname could not be resolved.",
        ) from exception
    if not addresses:
        raise ResourceActionError(
            "link_inaccessible",
            "The link hostname could not be resolved.",
        )
    for address in addresses:
        resolved = ipaddress.ip_address(address[4][0])
        if not resolved.is_global:
            raise UrlValidationError(
                "unsafe_url",
                "The link resolves to a private or local network address.",
            )


def retrieve_link(
    link: ValidatedLink,
    *,
    youtube_api_key: str | None,
    max_bytes: int,
) -> LinkSnapshot:
    if link.source_type == "youtube":
        return _retrieve_youtube(link, youtube_api_key, max_bytes)
    if link.source_type == "github_repository":
        return _retrieve_github(link, max_bytes)
    return _retrieve_webpage(link, max_bytes)


def _safe_get_json(url: str, max_bytes: int, headers: dict | None = None) -> dict:
    response = _safe_get(url, max_bytes=max_bytes, headers=headers)
    try:
        return json.loads(response)
    except json.JSONDecodeError as exception:
        raise ResourceActionError(
            "link_inaccessible",
            "The public metadata response was not valid JSON.",
        ) from exception


def _safe_get(
    url: str,
    *,
    max_bytes: int,
    headers: dict | None = None,
) -> str:
    current = url
    request_headers = {
        "Accept": "text/html,application/json,text/plain;q=0.9",
        "User-Agent": "ZeroBacklog/0.1 (+public-resource-readiness)",
        **(headers or {}),
    }
    with httpx.Client(follow_redirects=False, timeout=12.0, trust_env=True) as client:
        for _ in range(4):
            validated = validate_link(current)
            port = urlsplit(current).port or (
                443 if urlsplit(current).scheme == "https" else 80
            )
            assert_public_hostname(validated.hostname, port)
            try:
                with client.stream("GET", current, headers=request_headers) as response:
                    if response.status_code in REDIRECT_CODES:
                        location = response.headers.get("location")
                        if not location:
                            raise ResourceActionError(
                                "link_inaccessible",
                                "The link returned an invalid redirect.",
                            )
                        current = urljoin(current, location)
                        continue
                    if response.status_code in {401, 403, 404, 410, 451}:
                        raise ResourceActionError(
                            "link_inaccessible",
                            "The public content is unavailable or access-restricted.",
                        )
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise ResourceActionError(
                                "link_too_large",
                                "The page exceeds the safe snapshot limit.",
                            )
                    encoding = response.encoding or "utf-8"
                    return bytes(body).decode(encoding, errors="replace")
            except ResourceActionError:
                raise
            except httpx.HTTPError as exception:
                raise ResourceActionError(
                    "link_inaccessible",
                    "The public content could not be retrieved.",
                ) from exception
    raise ResourceActionError(
        "link_inaccessible",
        "The link redirected too many times.",
    )


def _retrieve_youtube(
    link: ValidatedLink,
    api_key: str | None,
    max_bytes: int,
) -> LinkSnapshot:
    video_id = _youtube_video_id(link.normalized_url)
    if not video_id:
        return _inaccessible("The YouTube video ID could not be identified.")
    if not api_key:
        return _inaccessible(
            "YouTube metadata is unavailable because the Data API is not configured."
        )
    query = urlencode(
        {
            "part": "snippet,contentDetails,status",
            "id": video_id,
            "key": api_key,
        }
    )
    try:
        payload = _safe_get_json(
            f"https://www.googleapis.com/youtube/v3/videos?{query}",
            max_bytes,
        )
    except ResourceActionError as exception:
        return _inaccessible(exception.message)
    items = payload.get("items") or []
    if not items:
        return _inaccessible(
            "The video is private, removed, invalid, or unavailable to the API."
        )
    item = items[0]
    snippet = item.get("snippet") or {}
    details = item.get("contentDetails") or {}
    status = item.get("status") or {}
    if status.get("privacyStatus") != "public":
        return _inaccessible("The YouTube video is not publicly accessible.")
    title = str(snippet.get("title") or f"YouTube video {video_id}")
    description = str(snippet.get("description") or "")
    channel = str(snippet.get("channelTitle") or "") or None
    duration = parse_iso_duration(str(details.get("duration") or ""))
    links = tuple(sorted(set(LINK_PATTERN.findall(description))))[:50]
    text = (
        f"# {title}\n\nChannel: {channel or 'Unknown'}\n"
        f"Duration seconds: {duration if duration is not None else 'Unknown'}\n\n"
        f"## Video description\n{description}\n\n"
        f"## Links from description\n" + "\n".join(links)
    ).strip()
    relevant, reason = is_coding_relevant(text)
    if not relevant:
        return LinkSnapshot(
            title=title,
            description=description or None,
            author=channel,
            duration_seconds=duration,
            outbound_links=links,
            text=text,
            status="irrelevant",
            explanation="Irrelevant — the available video metadata is not coding-focused.",
            technical_reason=reason,
            confidence=0.75,
            summary=summarize_text(description or title),
        )
    return LinkSnapshot(
        title=title,
        description=description or None,
        author=channel,
        duration_seconds=duration,
        outbound_links=links,
        text=text,
        status="partial",
        explanation=(
            "Metadata processed. Spoken video content was not analyzed because "
            "no transcript was available."
        ),
        technical_reason=(
            "YouTube Data API title, description, channel, duration, and public "
            "description links were retrieved. No transcript content was supplied."
        ),
        confidence=0.72,
        summary=summarize_text(description or title),
    )


def _retrieve_github(link: ValidatedLink, max_bytes: int) -> LinkSnapshot:
    parts = [part for part in urlsplit(link.normalized_url).path.split("/") if part]
    if len(parts) < 2:
        return _inaccessible("A GitHub repository URL must include owner and repository.")
    owner, repository = parts[:2]
    api_url = f"https://api.github.com/repos/{owner}/{repository}"
    headers = {"Accept": "application/vnd.github+json"}
    try:
        metadata = _safe_get_json(api_url, max_bytes, headers=headers)
        try:
            readme = _safe_get(
                f"{api_url}/readme",
                max_bytes=max_bytes,
                headers={"Accept": "application/vnd.github.raw+json"},
            )
        except ResourceActionError:
            readme = ""
    except ResourceActionError as exception:
        return _inaccessible(exception.message)
    title = str(metadata.get("full_name") or f"{owner}/{repository}")
    description = str(metadata.get("description") or "")
    author = str((metadata.get("owner") or {}).get("login") or "") or None
    topics = metadata.get("topics") or []
    language = metadata.get("language")
    text = (
        f"# {title}\n\n{description}\n\n"
        f"Language: {language or 'Unknown'}\n"
        f"Topics: {', '.join(str(topic) for topic in topics)}\n\n"
        f"## README\n{readme}"
    ).strip()
    relevant, reason = is_coding_relevant(text)
    status = "ready" if relevant and len(readme) >= 100 else (
        "partial" if relevant else "irrelevant"
    )
    explanation = {
        "ready": "Ready — repository metadata and README were retrieved.",
        "partial": "Partial — repository metadata was retrieved, but the README was limited.",
        "irrelevant": "Irrelevant — the repository does not appear focused on coding preparation.",
    }[status]
    return LinkSnapshot(
        title=title,
        description=description or None,
        author=author,
        duration_seconds=None,
        outbound_links=(),
        text=text,
        status=status,
        explanation=explanation,
        technical_reason=reason,
        confidence=0.9 if status == "ready" else 0.7,
        summary=summarize_text(description or readme),
    )


def _retrieve_webpage(link: ValidatedLink, max_bytes: int) -> LinkSnapshot:
    try:
        html = _safe_get(link.normalized_url, max_bytes=max_bytes)
    except ResourceActionError as exception:
        return _inaccessible(exception.message)
    parser = _PageParser()
    try:
        parser.feed(html)
    except Exception:
        return _inaccessible("The page markup could not be parsed safely.")
    title = parser.title.strip() or link.hostname
    text = "\n".join(parser.text_parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 80:
        return LinkSnapshot(
            title=title,
            description=parser.description,
            author=parser.author,
            duration_seconds=None,
            outbound_links=(),
            text=text,
            status="partial",
            explanation="Partial — the page exposed very little readable public text.",
            technical_reason="Fewer than 80 readable characters were extracted.",
            confidence=0.35,
            summary=summarize_text(text),
        )
    relevant, reason = is_coding_relevant(
        f"{title}\n{parser.description or ''}\n{text}"
    )
    status = "ready" if relevant else "irrelevant"
    return LinkSnapshot(
        title=title,
        description=parser.description,
        author=parser.author,
        duration_seconds=None,
        outbound_links=(),
        text=text[:120_000],
        status=status,
        explanation=(
            "Ready — public page text and metadata were retrieved."
            if relevant
            else "Irrelevant — this page appears unrelated to coding preparation."
        ),
        technical_reason=reason,
        confidence=0.88 if relevant else 0.8,
        summary=summarize_text(parser.description or text),
    )


def _youtube_video_id(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.hostname == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif parsed.path.startswith(("/shorts/", "/embed/")):
        parts = [part for part in parsed.path.split("/") if part]
        candidate = parts[1] if len(parts) > 1 else ""
    else:
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", candidate) else None


def parse_iso_duration(value: str) -> int | None:
    match = ISO_DURATION.fullmatch(value)
    if not match:
        return None
    parts = {name: int(number or 0) for name, number in match.groupdict().items()}
    return (
        parts["days"] * 86_400
        + parts["hours"] * 3_600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def _inaccessible(reason: str) -> LinkSnapshot:
    return LinkSnapshot(
        title="Unavailable public resource",
        description=None,
        author=None,
        duration_seconds=None,
        outbound_links=(),
        text="",
        status="inaccessible",
        explanation="Inaccessible — the public content could not be retrieved.",
        technical_reason=reason,
        confidence=None,
        summary=None,
    )
