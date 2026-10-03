"""Reading a book's structure from its own bookmarks.

The thing being protected here is that a chapter in the syllabus is a chapter in the
book — the whole reason this is read rather than generated.
"""

import pymupdf
import pytest

from app.outline import BOILERPLATE, read_outline


def build(tmp_path, toc):
    path = tmp_path / "book.pdf"
    document = pymupdf.open()
    for _ in range(40):
        document.new_page()
    document.set_toc(toc)
    document.save(path)
    document.close()
    return str(path)


@pytest.fixture
def book(tmp_path):
    """Two chapters, laid out the way publishers actually do it: the chapter number
    is its own entry and the title follows."""
    return build(
        tmp_path,
        [
            [1, "1", 5],
            [1, "Understanding TypeScript", 5],
            [1, "Technical requirements", 6],
            [1, "What is TypeScript?", 7],
            [2, "Why it matters", 9],
            [1, "Summary", 12],
            [1, "2", 15],
            [1, "Exploring Types", 15],
            [1, "Union types", 17],
            [1, "Get this book's PDF version and more", 25],
        ],
    )


def test_chapters_come_from_the_bookmarks(book):
    chapters = read_outline(book)

    assert [c.number for c in chapters] == [1, 2]
    assert chapters[0].title == "Understanding TypeScript"
    assert chapters[1].title == "Exploring Types"


def test_a_chapter_ends_where_the_next_begins(book):
    chapters = read_outline(book)

    assert chapters[0].page_start == 5
    assert chapters[0].page_end == 14
    assert chapters[1].page_start == 15


def test_boilerplate_headings_are_dropped(book):
    titles = [s.title for s in read_outline(book)[0].sections]

    assert "Technical requirements" not in titles
    assert "Summary" not in titles
    assert "What is TypeScript?" in titles


def test_level_two_headings_are_kept():
    """Publishers are inconsistent about levels, and filtering to level 1 silently
    drops whole subjects."""
    assert BOILERPLATE.match("Summary")
    assert not BOILERPLATE.match("Why it matters")


def test_deeper_headings_are_kept_as_candidates(book):
    titles = [s.title for s in read_outline(book)[0].sections]

    assert "Why it matters" in titles


def test_sections_get_page_ranges(book):
    sections = read_outline(book)[0].sections

    assert sections[0].page_start == 7
    assert sections[0].page_end == sections[1].page_start - 1


def test_a_pdf_without_bookmarks_yields_nothing(tmp_path):
    path = tmp_path / "flat.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()

    assert read_outline(str(path)) == []


def test_a_promotional_chapter_is_excluded(tmp_path):
    path = build(
        tmp_path,
        [
            [1, "1", 5],
            [1, "Real Chapter", 5],
            [1, "A topic", 6],
            [1, "2", 20],
            [1, "Unlock Your Exclusive Benefits", 20],
            [1, "A bonus", 21],
        ],
    )

    chapters = read_outline(path)

    assert [c.title for c in chapters] == ["Real Chapter"]
