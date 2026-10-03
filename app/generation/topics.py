"""One chapter -> its topic list.

The book's own headings do most of the work, so this call only has to merge what is
split too fine and drop what teaches nothing. It runs once per chapter, on the
chapter text, and writes that text to the cache the content calls then read from.
"""

from app.config import get_settings
from app.generation.client import parse_structured
from app.generation.prompts import TOPICS_SYSTEM, topics_user_text
from app.schemas import ChapterTopics, ChapterTopicsRequest


async def generate_chapter_topics(request: ChapterTopicsRequest) -> ChapterTopics:
    settings = get_settings()
    return await parse_structured(
        model=settings.outline_model,
        system=TOPICS_SYSTEM,
        source_text=request.text,
        user_text=topics_user_text(
            chapter_number=request.chapter_number,
            chapter_title=request.chapter_title,
            headings=[heading.title for heading in request.headings],
        ),
        output_format=ChapterTopics,
        effort="medium",
        # First call for this chapter: it pays for the cache the topic calls read.
        cache_source=True,
        max_tokens=4000,
    )
