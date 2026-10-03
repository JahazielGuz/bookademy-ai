"""Turning a PDF into text a model can learn from.

No page images. A 626-page book is 1.44M tokens when every page is rendered, and
268k as text — and for a programming book the text is the payload, because code
carries in characters. Figures are handled separately and only where they earn it.

Two things this does that a plain text dump does not:

- **Code is detected by font, not guessed.** Technical books set code in a
  monospace face, so a run of monospace lines is a listing and a monospace word
  inside a sentence is an inline mention. The model receives fenced code rather
  than prose with code smeared through it, which is most of what makes a generated
  exercise worth doing.
- **Publisher watermarks are stripped.** Copies are often tagged with per-buyer
  markers injected mid-word ("filter is idx_80b9bbabsimilar to find"). Left in,
  they end up inside generated lessons.
"""

import math
import re
from dataclasses import dataclass

import pymupdf

# Per-copy tracking markers injected into the text layer by some publishers.
WATERMARK = re.compile(r"idx_[0-9a-f]{8}")

MONOSPACE_HINTS = ("consolas", "courier", "mono", "menlo", "inconsolata")

# A line is code when most of its visible characters are monospace.
CODE_LINE_RATIO = 0.6
# ...and a fence needs a run of them, so one monospace word in a sentence stays inline.
MIN_CODE_RUN = 2

FIGURE_CAPTION = re.compile(r"^\s*(Figure|Fig\.)\s+\d+[.\d]*", re.IGNORECASE)

# Rendered at 2x: legible for labelled diagrams, where the docs warn that images
# under roughly 200px invite mistakes, and still only a few hundred visual tokens.
FIGURE_SCALE = 2.0

# ...but capped, because cost is dimensions and a full-page diagram at 2x is a
# thousand tokens on its own. Targeting a size beats trusting a multiplier.
FIGURE_MAX_EDGE_PX = 1000


def is_monospace(font: str) -> bool:
    lowered = font.lower()
    return any(hint in lowered for hint in MONOSPACE_HINTS)


def visual_tokens(width: int, height: int) -> int:
    """What an image costs: ceil(w/28) * ceil(h/28) 28x28 patches."""
    return math.ceil(width / 28) * math.ceil(height / 28)


@dataclass(frozen=True)
class Line:
    plain: str
    """The raw text, used when the line is part of a code listing."""
    inline: str
    """The text with monospace words wrapped in backticks, used in prose."""
    is_code: bool


def _lines(page: pymupdf.Page) -> list[Line]:
    lines: list[Line] = []
    for block in page.get_text("dict")["blocks"]:
        for raw in block.get("lines", []):
            spans = raw.get("spans", [])
            if not spans:
                continue

            plain = "".join(span["text"] for span in spans)
            if not plain.strip():
                continue

            visible = len(plain.replace(" ", ""))
            mono = sum(
                len(span["text"].replace(" ", "")) for span in spans if is_monospace(span["font"])
            )
            inline = "".join(
                f"`{span['text']}`"
                if is_monospace(span["font"]) and span["text"].strip()
                else span["text"]
                for span in spans
            )
            lines.append(
                Line(
                    plain=plain,
                    inline=inline,
                    is_code=visible > 0 and mono / visible > CODE_LINE_RATIO,
                )
            )
    return lines


def page_markdown(page: pymupdf.Page) -> str:
    """One page as Markdown, with listings fenced and inline code backticked."""
    lines = _lines(page)
    out: list[str] = []
    index = 0

    while index < len(lines):
        run = index
        while run < len(lines) and lines[run].is_code:
            run += 1

        if run - index >= MIN_CODE_RUN:
            body = "\n".join(line.plain for line in lines[index:run])
            out.append(f"```\n{body}\n```")
            index = run
        else:
            out.append(lines[index].inline)
            index += 1

    return WATERMARK.sub("", "\n".join(out))


Source = str | bytes
"""A path on disk, or the bytes of an upload that was never written to one."""


def _open(source: Source) -> pymupdf.Document:
    if isinstance(source, bytes):
        return pymupdf.open(stream=source, filetype="pdf")
    return pymupdf.open(source)


def document_markdown(source: Source, first_page: int = 1, last_page: int | None = None) -> str:
    """Pages `first_page` to `last_page` inclusive, 1-indexed, as Markdown.

    Page-ranged so a topic can be sent its own chapter instead of the whole book.
    """
    with _open(source) as document:
        last = last_page or document.page_count
        start = max(1, first_page)
        end = min(document.page_count, last)
        pages = [page_markdown(document[number - 1]) for number in range(start, end + 1)]
    return "\n\n".join(pages)


def page_count(source: Source) -> int:
    with _open(source) as document:
        return document.page_count


@dataclass(frozen=True)
class Figure:
    """One diagram, cropped from the page. Never a whole page."""

    caption: str
    page: int
    png: bytes
    width: int
    height: int

    @property
    def tokens(self) -> int:
        return visual_tokens(self.width, self.height)


def _caption_blocks(page: pymupdf.Page) -> list[tuple[str, pymupdf.Rect]]:
    """Captions are single lines, so they are matched per line rather than per block."""
    found = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line.get("spans", []))
            if FIGURE_CAPTION.match(text):
                found.append((text.strip(), pymupdf.Rect(line["bbox"])))
    return found


def _figure_rect(page: pymupdf.Page, caption: pymupdf.Rect) -> pymupdf.Rect | None:
    """The drawing sits in the empty band between the previous text and the caption.

    Cropping to that band is what keeps this to the graph itself rather than the
    page around it.
    """
    # Only text blocks count. The dict also contains image blocks, and the figure
    # itself sits directly above its caption — measuring to that would collapse the
    # band to nothing and crop away the very thing being extracted.
    above = [
        pymupdf.Rect(block["bbox"]).y1
        for block in page.get_text("dict")["blocks"]
        if block.get("type") == 0 and pymupdf.Rect(block["bbox"]).y1 < caption.y0 - 2
    ]
    top = max(above) if above else page.rect.y0
    rect = pymupdf.Rect(page.rect.x0, top, page.rect.x1, caption.y0)
    # A band only a few points tall holds no diagram, just line spacing.
    return rect if rect.height > 20 else None


def figures(source: Source, first_page: int = 1, last_page: int | None = None) -> list[Figure]:
    """Every captioned figure in a page range, cropped and rendered.

    Rendered at FIGURE_SCALE because a diagram's labels have to stay legible: the
    vision docs warn that images under roughly 200px invite mistakes. The cost is a
    few hundred visual tokens each, which is why only figures are rendered and the
    pages around them are not.
    """
    found: list[Figure] = []
    with _open(source) as document:
        last = last_page or document.page_count
        for number in range(max(1, first_page), min(document.page_count, last) + 1):
            page = document[number - 1]
            for caption, caption_rect in _caption_blocks(page):
                rect = _figure_rect(page, caption_rect)
                if rect is None:
                    continue
                longest = max(rect.width, rect.height)
                scale = min(FIGURE_SCALE, FIGURE_MAX_EDGE_PX / longest) if longest else 1.0
                pixmap = page.get_pixmap(clip=rect, matrix=pymupdf.Matrix(scale, scale))
                found.append(
                    Figure(
                        caption=caption,
                        page=number,
                        png=pixmap.tobytes("png"),
                        width=pixmap.width,
                        height=pixmap.height,
                    )
                )
    return found
