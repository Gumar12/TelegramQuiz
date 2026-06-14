"""Repair known review items into an OpenAI clean output file."""
from __future__ import annotations

import json
from pathlib import Path

from backend.parser import load_json
from backend.validator import validate_all


def main() -> None:
    clean_path = Path("19_lunch_openai.json")
    data = json.loads(clean_path.read_text(encoding="utf-8"))
    questions = data["questions"]

    if not any(item.get("source_item_id") == 215 for item in questions):
        questions.insert(
            10,
            {
                "question": "Хан, правивший в 1598 году",
                "correct_answer": "Есим",
                "correct_answers": [],
                "options": ["Есим", "Турсун", "Тауекель", "Жангир"],
                "correct": 1,
                "explanation": "В контексте указан хан Есим.",
                "explanation_full": "В контексте указан хан Есим.",
                "quality_flags": [],
                "source_item_id": 215,
                "date": "19 мая",
                "section": "ОБЕД",
                "context_title": "",
                "context": "",
                "media": [],
                "type": "simple_quiz",
                "source": "manual_repair",
            },
        )

    clean_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    validate_all(load_json(clean_path))
    print(f"OK: {len(data['questions'])} questions in {clean_path}")


if __name__ == "__main__":
    main()
