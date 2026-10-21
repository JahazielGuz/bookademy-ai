"""One document -> the few lines a learner reads before starting it.

The smallest call in the service: the chapter list and a slice of the book's opening
pages, in; two sentences and a handful of outcomes, out. It runs once per document,
without thinking, so it is over in seconds.
"""

from app.config import get_settings
from app.generation.client import parse_structured
from app.generation.prompts import OVERVIEW_SYSTEM, overview_user_text
from app.schemas import Overview, OverviewRequest, OverviewResponse

# Enough of the opening for a preface to state the book's aim, and not so much that a
# cheap call turns into an expensive one.
MAX_OPENING_CHARS = 12_000


async def generate_overview(request: OverviewRequest) -> OverviewResponse:
    settings = get_settings()
    parsed, usage = await parse_structured(
        model=settings.outline_model,
        system=OVERVIEW_SYSTEM,
        source_text=request.opening_text[:MAX_OPENING_CHARS],
        user_text=overview_user_text(
            title=request.title,
            chapter_titles=request.chapter_titles,
            language=request.language,
        ),
        thinking=settings.outline_thinking,
        output_format=Overview,
        # Two sentences and five phrases; the ceiling is headroom, not a target.
        max_output_tokens=2000,
    )
    return OverviewResponse(summary=parsed.summary, outcomes=parsed.outcomes, usage=usage)
