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


def test_the_schemas_carry_no_array_bounds():
    """Which JSON Schema keywords a provider accepts varies, and a rejected schema
    fails every call where a rejected response fails only one. Bounds are therefore
    enforced in validators, not in the schema."""
    import json

    from app.schemas import ChapterTopics, TopicContent

    for model in (ChapterTopics, TopicContent):
        text = json.dumps(model.model_json_schema())
        for keyword in ("minItems", "maxItems", "minLength", "maxLength"):
            assert keyword not in text, f"{model.__name__} still carries {keyword}"


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
