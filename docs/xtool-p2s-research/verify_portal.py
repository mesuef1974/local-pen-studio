"""Dependency-free structural/link check for the local xTool P2S portal."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
FORBIDDEN_VIDEO_ELEMENTS = {"video", "iframe", "embed", "object", "source"}


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.html_attrs: dict[str, str | None] = {}
        self.ids: set[str] = set()
        self.duplicate_ids: set[str] = set()
        self.links: list[str] = []
        self.stylesheets: list[str] = []
        self.images_without_alt = 0
        self.title_text = ""
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.tags.append(tag)
        if tag == "html":
            self.html_attrs = values
        if tag == "title":
            self.in_title = True
        element_id = values.get("id")
        if element_id:
            if element_id in self.ids:
                self.duplicate_ids.add(element_id)
            self.ids.add(element_id)
        if tag in {"a", "link", "script"}:
            reference = values.get("href") if tag != "script" else values.get("src")
            if reference:
                self.links.append(reference)
            if tag == "link" and "stylesheet" in (values.get("rel") or "").split():
                self.stylesheets.append(reference or "")
        if tag == "img" and not values.get("alt", "").strip():
            self.images_without_alt += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_text += data.strip()


def main() -> int:
    failures: list[str] = []
    pages = sorted(ROOT.glob("*.html"))
    page_indexes: dict[Path, Page] = {}
    for path in pages:
        parser = Page()
        parser.feed(path.read_text(encoding="utf-8"))
        parser.close()
        page_indexes[path.resolve()] = parser
        if parser.html_attrs.get("lang") != "ar" or parser.html_attrs.get("dir") != "rtl":
            failures.append(f"{path.name}: expected html lang=ar dir=rtl")
        if not parser.title_text:
            failures.append(f"{path.name}: missing document title")
        required_styles = {"../coordination/assets/identity.css", "assets/portal.css"}
        if not required_styles.issubset(parser.stylesheets):
            failures.append(f"{path.name}: missing shared identity or portal stylesheet")
        if parser.images_without_alt:
            failures.append(f"{path.name}: {parser.images_without_alt} image(s) missing alt text")
        if "main" not in parser.tags:
            failures.append(f"{path.name}: missing main landmark")
        if parser.duplicate_ids:
            failures.append(f"{path.name}: duplicate IDs {sorted(parser.duplicate_ids)}")
        if path.name == "user-experiences-ar.html":
            source = path.read_text(encoding="utf-8")
            if "class=\"nav\"" not in source or "aria-current=\"page\"" not in source:
                failures.append("user-experiences-ar.html: missing shared current-page navigation")
            if "<style>" in source or "style=\"" in source:
                failures.append("user-experiences-ar.html: page-specific inline styles found")
        for reference in parser.links:
            parsed = urlparse(reference)
            if parsed.scheme or reference.startswith("//") or reference.startswith("#") or parsed.netloc:
                continue
            target = (path.parent / parsed.path).resolve()
            if not target.is_relative_to(REPO_ROOT.resolve()):
                failures.append(f"{path.name}: local path escapes repository: {reference}")
            elif not target.exists():
                failures.append(f"{path.name}: missing local link: {reference}")
            elif parsed.fragment and target.suffix == ".html":
                linked_page = page_indexes.get(target)
                if linked_page is None:
                    linked_page = Page()
                    linked_page.feed(target.read_text(encoding="utf-8"))
                if parsed.fragment not in linked_page.ids:
                    failures.append(f"{path.name}: missing local fragment: {reference}")

    video_page = ROOT / "video-library-ar.html"
    video = page_indexes.get(video_page.resolve())
    if video is None:
        failures.append("video-library-ar.html: page is missing")
    else:
        present = FORBIDDEN_VIDEO_ELEMENTS.intersection(video.tags)
        if present:
            failures.append(f"video-library-ar.html: media elements found: {sorted(present)}")
        if video.tags.count("table") != 1:
            failures.append(f"video-library-ar.html: expected exactly one table, found {video.tags.count('table')}")
        if video.tags.count("tbody") != 1:
            failures.append("video-library-ar.html: expected a single metadata table body")

    print(f"HTML pages checked: {len(pages)}")
    print(f"Pages using shared visual identity: {sum({'../coordination/assets/identity.css', 'assets/portal.css'}.issubset(p.stylesheets) for p in page_indexes.values())}/{len(pages)}")
    print(f"Broken local links/fragments: {sum('local' in x or 'link' in x for x in failures)}")
    print(f"Failures: {len(failures)}")
    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        return 1
    print("PASS portal structure, RTL metadata, local links, and video-table constraints")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
