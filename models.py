"""Pydantic-модель одного вопроса квиза.

Используется и для валидации входного JSON, и как типизированный объект
в `flow.py`.
"""
from pydantic import BaseModel, Field, field_validator, model_validator


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=10)
    correct: int = Field(ge=1)
    explanation: str = Field(default="", max_length=200)

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
        if not (1 <= self.correct <= len(self.options)):
            raise ValueError(
                f"correct={self.correct} out of range 1..{len(self.options)}"
            )
        return self
