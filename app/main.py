"""The AI service. Stateless: it holds no database and remembers nothing between
calls. bookademy-core owns every row that results from these responses.

The PDF is read here once, into text, and never sent to a model. Handing the API a
PDF makes it render every page as an image as well as reading the text, which for a
600-page book is roughly four times the tokens for pages of prose where the picture
adds nothing.
"""

import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from openai import APIConnectionError, APIStatusError

from app.config import Settings, get_settings
from app.extraction import document_markdown, page_count
from app.generation.client import NotConfigured, Refused, Truncated
from app.generation.overview import generate_overview
from app.generation.topic import generate_topic_content
from app.generation.topics import generate_chapter_topics
from app.outline import read_outline
from app.schemas import (
    Chapter,
    ChapterTopicsRequest,
    ChapterTopicsResponse,
    DocumentResponse,
    Heading,
    OverviewRequest,
    OverviewResponse,
    TopicContentRequest,
    TopicContentResponse,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="bookademy-ai", version="0.3.0")

MAX_UPLOAD_BYTES = 64 * 1024 * 1024


async def require_service_token(
    x_service_token: str = Header(default=""),
    settings: Settings = Depends(get_settings),
) -> None:
    """Only bookademy-core may call this service; it is never exposed to browsers."""
    if x_service_token != settings.service_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad or missing X-Service-Token")


@app.exception_handler(NotConfigured)
async def not_configured(request: Request, exc: NotConfigured) -> JSONResponse:
    """A misconfigured service should say so, not return a stack trace."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/v1/documents",
    response_model=DocumentResponse,
    dependencies=[Depends(require_service_token)],
)
async def read_document(file: UploadFile) -> DocumentResponse:
    """Read the PDF: its structure, and its text page by page.

    No model is involved. The chapters come from the document's own bookmarks, which
    is exact and free where asking a model to outline hundreds of pages is neither.
    """
    if file.content_type != "application/pdf":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only application/pdf is accepted"
        )

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"PDF is {len(data) // 1024 // 1024}MB; the limit is 64MB",
        )

    try:
        total = page_count(data)
        pages = [document_markdown(data, number, number) for number in range(1, total + 1)]
        outline = read_outline(data)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Could not read this file as a PDF: {exc}"
        ) from exc

    chapters = [
        Chapter(
            number=chapter.number,
            title=chapter.title,
            page_start=chapter.page_start,
            page_end=chapter.page_end,
            headings=[
                Heading(title=s.title, page_start=s.page_start, page_end=s.page_end)
                for s in chapter.sections
            ],
        )
        for chapter in outline
    ]

    return DocumentResponse(
        page_count=total, chapters=chapters, pages=pages, has_outline=bool(chapters)
    )


@app.post(
    "/v1/overview",
    response_model=OverviewResponse,
    dependencies=[Depends(require_service_token)],
)
async def overview(request: OverviewRequest) -> OverviewResponse:
    return await _guarded(generate_overview(request))


@app.post(
    "/v1/chapter-topics",
    response_model=ChapterTopicsResponse,
    dependencies=[Depends(require_service_token)],
)
async def chapter_topics(request: ChapterTopicsRequest) -> ChapterTopicsResponse:
    return await _guarded(generate_chapter_topics(request))


@app.post(
    "/v1/topic-content",
    response_model=TopicContentResponse,
    dependencies=[Depends(require_service_token)],
)
async def topic_content(request: TopicContentRequest) -> TopicContentResponse:
    return await _guarded(generate_topic_content(request))


async def _guarded(awaitable):
    """Turn model and transport failures into statuses bookademy-core can act on.

    502 means retry, 422 means do not: nothing about retrying a refusal or a schema
    failure will change the outcome.
    """
    try:
        return await awaitable
    except Refused as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"detail": str(exc), "category": None},
        ) from exc
    except Truncated as exc:
        # Not worth retrying: the identical request truncates identically.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, {"detail": str(exc), "category": "truncated"}
        ) from exc
    except APIConnectionError as exc:
        logger.warning("could not reach the model server: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Could not reach the model server"
        ) from exc
    except APIStatusError as exc:
        logger.warning("model server returned %s: %s", exc.status_code, exc.message)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The model server failed") from exc
