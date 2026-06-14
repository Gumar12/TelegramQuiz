"""Pydantic-модель одного вопроса квиза.

Используется и для валидации входного JSON, и как типизированный объект
в `flow.py`.
"""
from pydantic import BaseModel, Field, field_validator, model_validator

INVISIBLE_CHARS = str.maketrans("", "", "\u200b\u200c\u200d\ufeff\u2060")


def clean_text_value(value: str) -> str:
    return " ".join(value.translate(INVISIBLE_CHARS).split())


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=10)
    correct: int | list[int]
    explanation: str = Field(default="", max_length=200)
    context_title: str = ""
    context: str = ""
    media: list[str] = Field(default_factory=list)

    @field_validator("question", "explanation", "context_title", "context", mode="before")
    @classmethod
    def clean_text_fields(cls, v: str) -> str:
        if isinstance(v, str):
            return clean_text_value(v)
        return v

    @field_validator("options", mode="before")
    @classmethod
    def clean_options(cls, v: list[str]) -> list[str]:
        if isinstance(v, list):
            return [clean_text_value(opt) if isinstance(opt, str) else opt for opt in v]
        return v

    @field_validator("options")
    @classmethod
    def options_unique_and_bounded(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("options must be unique")
        for opt in v:
            if not (1 <= len(opt) <= 100):
                raise ValueError(f"option length out of range (1..100): {opt!r}")
        return v

    @model_validator(mode="after")
    def correct_in_range(self):
        correct_values = self.correct if isinstance(self.correct, list) else [self.correct]
        if not correct_values:
            raise ValueError("correct must contain at least one index")
        if len(set(correct_values)) != len(correct_values):
            raise ValueError("correct indexes must be unique")
        for correct in correct_values:
            if not (1 <= correct <= len(self.options)):
                raise ValueError(
                    f"correct={correct} out of range 1..{len(self.options)}"
                )
        return self
