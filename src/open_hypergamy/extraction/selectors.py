"""Per-source CSS/XPath selectors with optional adaptive relocation (ADR-010).

Backed by Scrapling's parser (`scrapling.parser.Selector`, BSD-3). Only the parser is used: no
Scrapling fetcher, browser or stealth component is installed, so every request still goes through
`sources.fetch.Fetcher` and its SSRF, scope and throttling chain.

`extraction_hints.selectors` in a source YAML:

    selectors:
      adaptive: true            # remember matched elements; relocate them if the markup changes
      title: {css: "h1"}
      text:  {css: "main"}
      links: {xpath: "//ul[@class='jobs']//a"}

A configured selector that matches nothing raises `ParseError`: a parser failure is never a clean
empty scan. Adaptive relocation is best-effort (it can recover fewer elements than were saved), so
a relocated result is flagged to the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator
from scrapling.parser import Selector

from open_hypergamy.errors import ConfigurationError, ParseError

Field = Literal["title", "text", "links"]
_FIELDS: tuple[Field, ...] = ("title", "text", "links")
MAX_SELECTED_LINKS = 300


class SelectorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    css: str | None = None
    xpath: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> SelectorSpec:
        if (self.css is None) == (self.xpath is None):
            raise ValueError("give exactly one of css or xpath")
        return self


class SelectorHints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adaptive: bool = False
    title: SelectorSpec | None = None
    text: SelectorSpec | None = None
    links: SelectorSpec | None = None

    @model_validator(mode="after")
    def _something(self) -> SelectorHints:
        if not any((self.title, self.text, self.links)):
            raise ValueError("selectors needs at least one of title, text, links")
        return self


@dataclass(frozen=True)
class SelectorResult:
    title: str | None = None
    text: str | None = None
    link_hrefs: list[str] | None = None
    relocated: tuple[
        str, ...
    ] = ()  # fields recovered adaptively after the selector stopped matching


def parse_hints(extraction_hints: dict[str, Any]) -> SelectorHints | None:
    """Validate `extraction_hints['selectors']`; None when the source defines none."""
    raw = extraction_hints.get("selectors")
    if raw is None:
        return None
    try:
        return SelectorHints.model_validate(raw)
    except ValueError as e:
        raise ConfigurationError(f"invalid extraction_hints.selectors: {e}") from e


def _run(page: Selector, spec: SelectorSpec, identifier: str, adaptive: bool) -> Any:
    if spec.css is not None:
        return page.css(spec.css, identifier=identifier, adaptive=adaptive, auto_save=adaptive)
    assert spec.xpath is not None
    return page.xpath(spec.xpath, identifier=identifier, adaptive=adaptive, auto_save=adaptive)


def apply_selectors(
    html: str,
    *,
    url: str,
    hints: SelectorHints,
    source_key: str,
    storage_file: Path | None,
) -> SelectorResult:
    """Run the configured selectors. Adaptive mode needs `storage_file`; without it, it is off."""
    adaptive = hints.adaptive and storage_file is not None
    storage_args = {"storage_file": str(storage_file), "url": url} if adaptive else None
    page = Selector(html, url=url, adaptive=adaptive, storage_args=storage_args)
    values: dict[str, Any] = {}
    relocated: list[str] = []
    for name in _FIELDS:
        spec: SelectorSpec | None = getattr(hints, name)
        if spec is None:
            continue
        identifier = f"{source_key}:{name}"
        found = _run(page, spec, identifier, False)
        if not found and adaptive:
            found = _run(page, spec, identifier, True)
            if found:
                relocated.append(name)
        elif found and adaptive:
            _run(page, spec, identifier, True)  # refresh the stored fingerprint
        if not found:
            raise ParseError(
                f"selector for {name} matched nothing on {url}: {spec.css or spec.xpath}"
            )
        values[name] = found
    text = values.get("text")
    title = values.get("title")
    links = values.get("links")
    return SelectorResult(
        title=title[0].get_all_text(separator=" ", strip=True) or None if title else None,
        text="\n".join(el.get_all_text(separator="\n", strip=True) for el in text)
        if text
        else None,
        link_hrefs=_hrefs(links) if links else None,
        relocated=tuple(relocated),
    )


def _hrefs(found: Any) -> list[str]:
    out: list[str] = []
    for el in found:
        href = el.attrib.get("href")
        if href is None:  # selector pointed at a container: take its anchors
            out.extend(a.attrib["href"] for a in el.css("a[href]"))
        else:
            out.append(str(href))
    return out[:MAX_SELECTED_LINKS]
