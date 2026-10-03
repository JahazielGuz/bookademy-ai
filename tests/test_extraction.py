"""Extraction is what every generated lesson is built from, so the things that
would quietly degrade it are pinned here."""

import pymupdf
import pytest

from app.extraction import (
    WATERMARK,
    document_markdown,
    is_monospace,
    page_count,
    page_markdown,
    visual_tokens,
)


@pytest.fixture
def book(tmp_path):
    """A two-page PDF with prose, a code listing, and an inline code mention."""
    path = tmp_path / "book.pdf"
    document = pymupdf.open()

    page = document.new_page()
    page.insert_text((50, 60), "Arrays have a filter method.", fontname="times-roman", fontsize=11)
    page.insert_text((50, 90), "const items = [1, 2, 3]", fontname="courier", fontsize=10)
    page.insert_text((50, 105), "const big = items.filter(n => n > 1)", fontname="courier", fontsize=10)
    page.insert_text((50, 135), "That returns every match.", fontname="times-roman", fontsize=11)

    second = document.new_page()
    second.insert_text((50, 60), "A second page.", fontname="times-roman", fontsize=11)

    document.save(path)
    document.close()
    return str(path)


def test_monospace_fonts_are_recognised():
    assert is_monospace("Consolas")
    assert is_monospace("CourierNewPSMT")
    assert not is_monospace("Crimson-Pro")


def test_a_run_of_monospace_lines_becomes_a_fenced_block(book):
    markdown = document_markdown(book)

    assert "```" in markdown
    assert "const items = [1, 2, 3]" in markdown
    # Both code lines belong to the same fence, not two.
    assert markdown.count("```") == 2


def test_prose_is_not_fenced(book):
    markdown = document_markdown(book)

    assert "Arrays have a filter method." in markdown
    prose_index = markdown.index("Arrays have a filter")
    assert "```" not in markdown[:prose_index]


def test_a_page_range_excludes_other_pages(book):
    first_only = document_markdown(book, 1, 1)

    assert "A second page." not in first_only
    assert "Arrays have a filter method." in first_only


def test_a_range_past_the_end_is_clamped(book):
    markdown = document_markdown(book, 1, 99)

    assert "A second page." in markdown


def test_watermarks_are_stripped_from_mid_word():
    assert WATERMARK.sub("", "filter is idx_80b9bbabsimilar to find") == (
        "filter is similar to find"
    )


def test_a_watermark_pattern_does_not_eat_real_text():
    """Only the exact marker shape goes; identifiers that merely start with idx_ stay."""
    assert WATERMARK.sub("", "const idx_value = 1") == "const idx_value = 1"


def test_visual_tokens_follow_the_28_pixel_patch_rule():
    assert visual_tokens(1080, 356) == 507
    assert visual_tokens(28, 28) == 1
    # Partial patches round up.
    assert visual_tokens(29, 29) == 4


def test_page_count_is_read_without_loading_the_whole_document(book):
    assert page_count(book) == 2


def test_an_empty_page_produces_nothing(tmp_path):
    path = tmp_path / "blank.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()

    with pymupdf.open(str(path)) as opened:
        assert page_markdown(opened[0]) == ""


@pytest.fixture
def illustrated(tmp_path):
    """A page with prose, a drawing, and a caption under it."""
    path = tmp_path / "illustrated.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 60), "Here is how the request flows.", fontname="times-roman", fontsize=11)
    # A drawing between the prose and the caption, where a figure lives.
    page.draw_rect(pymupdf.Rect(60, 90, 400, 260), color=(0, 0, 0), width=2)
    page.insert_text((50, 290), "Figure 9.1 - Express request flow", fontname="times-roman", fontsize=9)
    page.insert_text((50, 330), "That is the whole pipeline.", fontname="times-roman", fontsize=11)
    document.save(path)
    document.close()
    return str(path)


def test_a_captioned_figure_is_found(illustrated):
    from app.extraction import figures

    found = figures(illustrated)

    assert len(found) == 1
    assert found[0].caption.startswith("Figure 9.1")
    assert found[0].page == 1


def test_the_crop_is_the_figure_not_the_page(illustrated):
    """The band between the prose above and the caption — not the whole page."""
    from app.extraction import figures

    figure = figures(illustrated)[0]
    page_height = 792  # default letter height in points

    assert figure.png.startswith(b"\x89PNG")
    # Rendered at most 2x, and well short of a full page.
    assert figure.height < page_height * 2 * 0.5


def test_a_figure_long_edge_is_capped(illustrated):
    from app.extraction import FIGURE_MAX_EDGE_PX, figures

    figure = figures(illustrated)[0]

    assert max(figure.width, figure.height) <= FIGURE_MAX_EDGE_PX


def test_figure_tokens_use_the_patch_rule(illustrated):
    from app.extraction import figures, visual_tokens

    figure = figures(illustrated)[0]

    assert figure.tokens == visual_tokens(figure.width, figure.height)


def test_a_page_with_no_caption_yields_no_figures(book):
    from app.extraction import figures

    assert figures(book) == []


def test_figures_are_limited_to_the_page_range(illustrated):
    from app.extraction import figures

    # The only figure is on page 1, so a range starting at 2 finds nothing.
    assert figures(illustrated, 2, 2) == []
