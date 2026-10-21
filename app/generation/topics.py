"""One chapter -> its topic list.

The book's own headings do most of the work, so this call only has to merge what is
split too fine and drop what teaches nothing. It runs once per chapter, on the whole
chapter text — the one call that does, which is why it runs without thinking: a long
chapter leaves little of the window for anything else.
"""

from app.config import get_settings
from app.generation.client import parse_structured
from app.generation.prompts import TOPICS_SYSTEM, topics_user_text
from app.schemas import ChapterTopics, ChapterTopicsRequest, ChapterTopicsResponse


async def generate_chapter_topics(request: ChapterTopicsRequest) -> ChapterTopicsResponse:
    settings = get_settings()
    parsed, usage = await parse_structured(
        model=settings.outline_model,
        system=TOPICS_SYSTEM,
        source_text=request.text,
        user_text=topics_user_text(
            chapter_number=request.chapter_number,
            chapter_title=request.chapter_title,
            headings=[heading.title for heading in request.headings],
            page_start=request.page_start,
            page_end=request.page_end,
        ),
        thinking=settings.outline_thinking,
        output_format=ChapterTopics,
        # A list of titles, summaries and page numbers; small by design, so the
        # chapter text can be as long as it is.
        max_output_tokens=4000,
    )
    return ChapterTopicsResponse(topics=parsed.topics, usage=usage)
