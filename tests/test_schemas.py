import pytest
from pydantic import ValidationError

from app.schemas import Exercise, ExerciseStep, QuizQuestion


def step(number: int, starter: str, expected: str) -> ExerciseStep:
    return ExerciseStep(
        number=number,
        instruction_markdown="Do the thing.",
        explanation_markdown="It does a thing.",
        starter_code=starter,
        expected_code=expected,
    )


def test_broken_step_chain_is_relinked():
    """The model is told steps are cumulative but does not always comply."""
    exercise = Exercise(
        title="Scopes",
        scenario_markdown="A paint shop.",
        language="python",
        steps=[
            step(1, "", "color = 'Red'"),
            step(2, "WRONG", "color = 'Red'\nprint(color)"),
        ],
    )
    assert exercise.steps[1].starter_code == exercise.steps[0].expected_code


def test_steps_are_renumbered_densely():
    exercise = Exercise(
        title="Scopes",
        scenario_markdown="A paint shop.",
        language="python",
        steps=[step(7, "", "a = 1"), step(9, "a = 1", "a = 1\nb = 2")],
    )
    assert [s.number for s in exercise.steps] == [1, 2]


def test_first_step_starter_is_left_alone():
    exercise = Exercise(
        title="Scopes",
        scenario_markdown="A paint shop.",
        language="python",
        steps=[step(1, "# given to you\n", "# given to you\nx = 1")],
    )
    assert exercise.steps[0].starter_code == "# given to you\n"


def test_quiz_answer_must_point_at_a_real_choice():
    with pytest.raises(ValidationError):
        QuizQuestion(
            prompt="Which?", choices=["a", "b"], correct_index=2, explanation="..."
        )


def test_the_schemas_the_api_receives_are_compliant():
    """Structured outputs reject most JSON Schema constraints.

    Pydantic emits several of them freely — `max_length` on a list becomes
    `maxItems`, which is not supported at all, and `min_length=2` becomes
    `minItems: 2`, where only 0 and 1 are allowed. The SDK rewrites them into the
    description on the way out, so this asserts the schema actually sent is clean
    rather than trusting that it is.
    """
    import json

    from anthropic.lib._parse._transform import transform_schema

    from app.schemas import ChapterTopics, TopicContent

    unsupported = {"maxItems", "minLength", "maxLength", "minimum", "maximum", "multipleOf"}

    def problems(node, path="$"):
        found = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key in unsupported:
                    found.append(f"{path}.{key}")
                if key == "minItems" and value not in (0, 1):
                    found.append(f"{path}.minItems={value}")
                found.extend(problems(value, f"{path}.{key}"))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                found.extend(problems(item, f"{path}[{index}]"))
        return found

    for model in (ChapterTopics, TopicContent):
        sent = transform_schema(model.model_json_schema())
        assert problems(sent) == [], f"{model.__name__} would be rejected: {problems(sent)}"

        # Every object must carry additionalProperties: false.
        text = json.dumps(sent)
        assert text.count('"type": "object"') == text.count('"additionalProperties": false')


def test_a_question_may_have_more_choices_than_asked_for():
    """The upper bound is guidance in the prompt, not a schema constraint, so a
    model returning six choices produces a usable question rather than a failure."""
    from app.schemas import QuizQuestion

    question = QuizQuestion(
        prompt="Which?",
        choices=["a", "b", "c", "d", "e", "f"],
        correct_index=5,
        explanation="...",
    )

    assert len(question.choices) == 6


def test_a_question_with_one_choice_is_still_rejected():
    import pytest
    from pydantic import ValidationError

    from app.schemas import QuizQuestion

    with pytest.raises(ValidationError):
        QuizQuestion(prompt="Which?", choices=["only"], correct_index=0, explanation="...")
