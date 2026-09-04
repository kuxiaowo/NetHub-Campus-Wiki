"""Public media URL generation shared by backend response formatters."""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from backend.config import settings


# Documents and archives intentionally stay outside this allowlist. They are
# downloaded through /api/files so authentication and download accounting are
# not bypassed by the public media endpoint.
PUBLIC_MEDIA_EXTENSIONS = {
    ".avif",
    ".avi",
    ".gif",
    ".jpeg",
    ".jpg",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".png",
    ".webm",
    ".webp",
}


def _configured_media_base() -> str:
    return str(settings.public_media_base_url or "").strip().rstrip("/")


def local_public_path(value: str | None) -> str | None:
    """Return a safe path relative to ``public/``.

    Besides the legacy ``/Photos/example.jpg`` form, URLs below the configured
    public media base are accepted. This keeps directory scanning working if an
    administrator saves a URL previously returned by the public API.
    """

    raw_value = str(value or "").strip().replace("\\", "/")
    if not raw_value:
        return None

    parsed = urlsplit(raw_value)
    if parsed.scheme or parsed.netloc:
        media_base = _configured_media_base()
        if not media_base:
            return None
        parsed_base = urlsplit(media_base)
        if (parsed.scheme.casefold(), parsed.netloc.casefold()) != (
            parsed_base.scheme.casefold(),
            parsed_base.netloc.casefold(),
        ):
            return None
        base_path = parsed_base.path.rstrip("/")
        if parsed.path == base_path:
            path_value = ""
        elif parsed.path.startswith(f"{base_path}/"):
            path_value = parsed.path[len(base_path) + 1 :]
        else:
            return None
    else:
        path_value = parsed.path.lstrip("/")

    try:
        relative = unquote(path_value)
    except (UnicodeDecodeError, ValueError):
        return None
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or "." in path.parts or ".." in path.parts:
        return None
    return path.as_posix()


def public_media_url(value: str | None) -> str | None:
    """Resolve a local image/video path against the backend media URL."""

    raw_value = str(value or "").strip()
    if not raw_value:
        return None

    parsed = urlsplit(raw_value)
    if parsed.scheme or parsed.netloc:
        return raw_value

    relative = local_public_path(raw_value)
    if relative is None or PurePosixPath(relative).suffix.casefold() not in PUBLIC_MEDIA_EXTENSIONS:
        return raw_value

    media_base = _configured_media_base()
    if not media_base:
        return raw_value

    encoded_path = quote(relative, safe="/-._~!$&'()*+,;=:@")
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{media_base}/{encoded_path}{query}{fragment}"
