# bookademy-ai

Turns a PDF into course content. Stateless: no database, no memory between calls.
`bookademy-core` owns every row that results from these responses.

## Endpoints

All three require `X-Service-Token`, matching `SERVICE_TOKEN`. This service is never
exposed to a browser.

| Endpoint | Does |
|---|---|
| `POST /v1/documents` | Uploads a PDF to the Anthropic Files API and returns `{file_id, page_count}`. Called once per document. |
| `POST /v1/syllabus` | `{file_id}` → the whole syllabus: chapters, and the topics within each. |
| `POST /v1/topic-content` | One topic → its lesson, quiz and exercises. Called once per topic. |

## Model choices

- **Syllabus: Opus 5.5 at `high` effort.** One call per document. Every per-topic
  call inherits this structure and a bad chapter split cannot be repaired later, so
  this is where the stronger model earns its price.
- **Topic content: Sonnet 5.5 at `medium` effort.** Called tens of times per
  document; this is where nearly all the spend lives.
- **The PDF is cached on the topic calls, not the syllabus call.** Caching costs
  1.25x to write and 0.1x to read, so it pays off across many calls on one model and
  loses money on a single call. The prompt-cache prefix is the document block plus a
  module-constant system prompt, which is why the prompts are constants and not
  f-strings.

Set `OUTLINE_MODEL` and `CONTENT_MODEL` to change either.

## The contract

`app/schemas.py` is the single source of truth for the shape of generated content.
`bookademy-core/curriculum/models.py` mirrors it, so a change here is a migration
there and a type change in `bookademy-web/lib/types.ts`.

Two things are enforced in code rather than trusted to the model:

- **Step chaining.** Every step's `starter_code` is overwritten with the previous
  step's `expected_code`. A broken chain means asking a learner to type into a buffer
  that never existed, and relinking is cheaper than a retry.
- **Quiz answers.** `correct_index` must point at a real choice.

## Failure modes

`422` means don't retry — the model declined, or its output did not fit the schema;
the identical request will do the identical thing. `502` means do retry.
