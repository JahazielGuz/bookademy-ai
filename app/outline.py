"""Reading a book's structure out of the document itself.

A textbook already contains its own syllabus: the PDF outline carries chapter
titles, section headings and the page each starts on. Reading it costs nothing,
cannot invent a chapter that is not in the book, and is exact where a model working
from 600 pages of prose can only be approximate.

Only books without a usable outline need a model, and that path is the fallback.
"""

import re
from dataclasses import dataclass

import pymupdf

from app.extraction import Source, _open

# Headings every technical publisher repeats that teach nothing.
BOILERPLATE = re.compile(
    r"^\s*(technical requirements|summary|further reading|references|index|"
    r"get this book|join our|share your thoughts|unlock your|why subscribe|"
    r"other books you may enjoy|preface|contributors|about the author|"
    r"about the reviewer|table of contents|packt)",
    re.IGNORECASE,
)


@dataclass
class Section:
    title: str
    page_start: int
    page_end: int


@dataclass
class ChapterOutline:
    number: int
    title: str
    page_start: int
    page_end: int
    sections: list[Section]


def _is_chapter_marker(title: str) -> bool:
    """Publishers commonly set the chapter number as its own outline entry, with
    the title in the next one."""
    return title.strip().isdigit()


def read_outline(source: Source) -> list[ChapterOutline]:
    """The book's chapters and their sections, or an empty list if it has no
    usable outline."""
    with _open(source) as document:
        toc = document.get_toc()
        page_total = document.page_count

    marks = [index for index, (_, title, _) in enumerate(toc) if _is_chapter_marker(title)]
    if len(marks) < 2:
        return []

    chapters: list[ChapterOutline] = []
    for position, start in enumerate(marks):
        number = int(toc[start][1].strip())
        if start + 1 >= len(toc):
            continue
        title = toc[start + 1][1].strip()
        page_start = toc[start][2]
        page_end = (
            toc[marks[position + 1]][2] - 1 if position + 1 < len(marks) else page_total
        )

        sections: list[Section] = []
        index = start + 2
        while index < len(toc) and not _is_chapter_marker(toc[index][1]):
            level, heading, page = toc[index]
            # Both levels are taken. Publishers are not consistent about them: in one
            # chapter a real topic is level 1, in the next the same kind of heading is
            # level 2, and filtering to level 1 silently drops whole subjects. The
            # per-chapter pass merges what is too fine rather than guessing here.
            if level <= 2 and not BOILERPLATE.match(heading):
                sections.append(Section(title=heading.strip(), page_start=page, page_end=page))
            index += 1

        for position_in_chapter, section in enumerate(sections):
            section.page_end = (
                sections[position_in_chapter + 1].page_start - 1
                if position_in_chapter + 1 < len(sections)
                else page_end
            )

        if sections and not BOILERPLATE.match(title):
            chapters.append(
                ChapterOutline(
                    number=number,
                    title=title,
                    page_start=page_start,
                    page_end=page_end,
                    sections=sections,
                )
            )

    return chapters
