# bookademy-ai

Turns a PDF into course content. Stateless: no database, no memory between calls.
`bookademy-core` owns every row that results from these responses.

## Endpoints

All three require `X-Service-Token`, matching `SERVICE_TOKEN`. This service is never
exposed to a browser.

| Endpoint | Does |
|---|---|
| `POST /v1/documents` | Reads a PDF into Markdown, one entry per page, plus its chapters and their page ranges. **No model is involved.** Called once per document. |
| `POST /v1/overview` | Title and chapter list → the two sentences and handful of outcomes shown above the syllabus. Called once per document, on the lightweight model; a fraction of a cent. |
| `POST /v1/chapter-topics` | A chapter's text and its own headings → 4–8 topics. Called once per chapter. |
| `POST /v1/topic-content` | A topic's text → its lesson, quiz and exercises. Called once per topic, and where nearly all the spend lives. |

## The PDF is never sent to a model

Handing the API a PDF makes it render **every page as an image** as well as reading
the text. For a 626-page book that is ~1.44M tokens against ~331k for the text alone.
So the document is read locally and only text goes over the wire:

- **Code is detected by font.** Technical books set code in a monospace face, so a run
  of monospace lines is a listing and a monospace word inside a sentence is an inline
  mention. The model receives fenced code rather than prose with code smeared through
  it.
- **Publisher watermarks are stripped.** Copies are tagged with per-buyer markers
  injected mid-word (`filter is idx_80b9bbabsimilar to find`). Left in, they end up
  inside generated lessons.
- **Figures are cropped, pages are not** — only the band between a caption and the
  text above it, capped at a 1000px long edge.

## Structure is read, not generated

Chapters, their titles and their page ranges come from the PDF's own bookmarks:
exact, free, and incapable of inventing a chapter the book does not have. A model is
only asked what the document cannot answer — which of a chapter's headings are really
one topic, and what each topic's lesson should say.

A PDF without bookmarks cannot be used. That is checked up front and reported.

## Configuration

| Variable | |
|---|---|
| `OPENAI_API_KEY` | Required. |
| `SERVICE_TOKEN` | Must match `bookademy-core/.env` exactly. |
| `OUTLINE_MODEL` | Merges a chapter's headings into topics. Default `gpt-5-mini`. |
| `CONTENT_MODEL` | Writes each topic. Default `gpt-5-mini`. |

Both default to mid-tier on purpose. A nano-class model is cheaper again, but it is
built for classification and routing, not for writing cumulative exercises where each
step has to build on the last and the code has to run. That is the one part of this
system where paying less shows.

Prompt caching is automatic and needs no annotation. What still matters is prompt
*order*: the source text leads and the per-call instruction trails, so the repeated
prefix stays identical across a chapter.

## The contract

`app/schemas.py` is the single source of truth for the shape of generated content.
`bookademy-core/curriculum/models.py` mirrors it, so a change here is a migration
there and a type change in `bookademy-web/lib/types.ts`.

Three things are enforced in code rather than trusted to the model:

- **Step chaining.** Every step's `starter_code` is overwritten with the previous
  step's `expected_code`. A broken chain means asking a learner to type into a buffer
  that never existed, and relinking is cheaper than a retry.
- **Quiz answers.** A question needs at least two choices and `correct_index` must
  point at one of them.
- **No array bounds in the emitted schema.** Which JSON Schema keywords a provider
  accepts varies, and the failure modes are not comparable: a rejected schema fails
  every call, where a rejected response fails one.

Every response carries a `usage` block — model, input tokens, cached input tokens,
output tokens — so `bookademy-core` can record what a run actually cost instead of
estimating it.

## Failure modes

`422` means don't retry — the model declined, or its output did not fit the schema;
the identical request will do the identical thing. `502` means do retry. `503` means
no credentials are configured.
