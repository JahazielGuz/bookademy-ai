"""The generated-content contract.

These models are the single source of truth for everything the AI service returns.
bookademy-core stores them verbatim, so a change here is a database migration there
and a type change in bookademy-web.

Nothing in this contract carries a PDF. The service is given text that was already
extracted from the document, because handing the API a PDF makes it render every
page as an image as well as reading the text — four times the tokens, for pages of
prose where the picture adds nothing.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Language = Literal["python", "javascript"]


# --- Structure read from the document, no model involved ---------------------


class Heading(BaseModel):
    """A section heading from the book's own table of contents."""

    title: str
    page_start: int
    page_end: int


class Chapter(BaseModel):
    number: int
    title: str
    page_start: int
    page_end: int
    headings: list[Heading]


class DocumentResponse(BaseModel):
    page_count: int
    chapters: list[Chapter]
    pages: list[str] = Field(
        description="One Markdown string per page, so any page range can be sliced later."
    )
    has_outline: bool = Field(
        description="False when the PDF carries no usable bookmarks and topics must be inferred."
    )


# --- Topics: one call per chapter --------------------------------------------


class Topic(BaseModel):
    title: str
    summary: str = Field(description="One or two sentences on what this topic covers.")
    key_points: list[str] = Field(description="The specific ideas a learner must come away with.")
    page_start: int
    page_end: int


class ChapterTopicsRequest(BaseModel):
    language: Language
    chapter_number: int
    chapter_title: str
    text: str = Field(description="The chapter's extracted Markdown.")
    headings: list[Heading] = Field(
        default_factory=list,
        description="The book's own headings for this chapter, as candidates to merge.",
    )


class ChapterTopics(BaseModel):
    topics: list[Topic] = Field(min_length=1)


# --- Topic content: one call per topic ---------------------------------------


class Lesson(BaseModel):
    """The left-hand pane: narrative, worked code, and a real scenario."""

    title: str
    body_markdown: str = Field(
        description=(
            "The explanation a learner reads before practising. Fenced code blocks are "
            "expected; they are read, not typed."
        )
    )


class QuizQuestion(BaseModel):
    prompt: str
    choices: list[str] = Field(min_length=2, max_length=5)
    correct_index: int
    explanation: str = Field(description="Why the correct choice is correct.")

    @model_validator(mode="after")
    def correct_index_in_range(self) -> "QuizQuestion":
        if not 0 <= self.correct_index < len(self.choices):
            raise ValueError("correct_index is outside the choices list")
        return self


class Quiz(BaseModel):
    questions: list[QuizQuestion] = Field(min_length=1)


class ExerciseStep(BaseModel):
    """One checkpoint. The learner types their way from starter_code to expected_code."""

    number: int
    instruction_markdown: str = Field(
        description="What to do in this step, in the imperative. One action."
    )
    explanation_markdown: str = Field(
        description="What the code being typed does, and where it would be used."
    )
    starter_code: str = Field(description="Editor content when the step opens.")
    expected_code: str = Field(description="Editor content once the step is complete.")
    hint: str | None = None


class Exercise(BaseModel):
    title: str
    scenario_markdown: str = Field(
        description="The concrete situation the exercise is set in, e.g. a small app being built."
    )
    language: Language
    steps: list[ExerciseStep] = Field(min_length=1)

    @model_validator(mode="after")
    def chain_the_steps(self) -> "Exercise":
        """Force every step to start where the previous one ended.

        The model is asked for this but does not reliably produce it, and a broken
        chain means a learner is asked to type into a buffer that never existed.
        Renumbering and relinking here is cheaper than a retry.
        """
        for index, step in enumerate(self.steps):
            step.number = index + 1
            if index > 0:
                step.starter_code = self.steps[index - 1].expected_code
        return self


class TopicContent(BaseModel):
    lesson: Lesson
    quiz: Quiz
    exercises: list[Exercise] = Field(min_length=1)


class TopicContentRequest(BaseModel):
    language: Language
    chapter_number: int
    chapter_title: str
    topic_title: str
    topic_summary: str
    key_points: list[str]
    text: str = Field(description="The chapter's extracted Markdown, cached across its topics.")
