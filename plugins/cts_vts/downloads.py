"""Discover downloadable CTS packages from the official Android page."""

from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlsplit


CTS_DOWNLOADS_URL = "https://source.android.com/docs/compatibility/cts/downloads"
ARCHIVE = re.compile(r"android-cts-(?P<revision>[0-9.]+_r\d+)-linux_x86-arm\.zip$")


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def _revision_sort_key(revision: str) -> tuple[tuple[int, ...], int]:
    version, release = revision.rsplit("_r", 1)
    return tuple(int(part) for part in version.split(".")), int(release)


def parse_cts_downloads(html: str) -> dict[str, str]:
    parser = _LinkParser()
    parser.feed(html)
    result: dict[str, str] = {}
    for url in parser.links:
        match = ARCHIVE.search(urlsplit(url).path)
        if match:
            result[match["revision"]] = url
    return dict(
        sorted(
            result.items(),
            key=lambda item: _revision_sort_key(item[0]),
            reverse=True,
        )
    )


def fetch_cts_downloads(timeout: int = 15) -> dict[str, str]:
    request = urllib.request.Request(CTS_DOWNLOADS_URL, headers={"User-Agent": "moulin-remote-client/cts-vts"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_cts_downloads(response.read().decode("utf-8", errors="replace"))
