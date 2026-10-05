"""One topic -> lesson, quiz and exercises.

Called once per topic, which is where nearly all the token spend lives. The chapter
text was cached by the topics call, so every one of these reads it at a tenth of the
price instead of sending it again.
"""

from app.config import get_settings
from app.generation.client import parse_structured
from app.generation.prompts import CONTENT_SYSTEM, content_user_text
from app.schemas import TopicContent, TopicContentRequest, TopicContentResponse


async def generate_topic_content(request: TopicContentRequest) -> TopicContentResponse:
    settings = get_settings()
    parsed, usage = await parse_structured(
        model=settings.content_model,
        system=CONTENT_SYSTEM,
        source_text=request.text,
        user_text=content_user_text(
            language=request.language,
            chapter_number=request.chapter_number,
            chapter_title=request.chapter_title,
            topic_title=request.topic_title,
            topic_summary=request.topic_summary,
            key_points=request.key_points,
        ),
        output_format=TopicContent,
        max_output_tokens=16000,
    )
    return TopicContentResponse(
        lesson=parsed.lesson, quiz=parsed.quiz, exercises=parsed.exercises, usage=usage
    )
