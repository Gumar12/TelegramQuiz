"""Create a corrected 19 May lunch clean JSON with proper context grouping."""
from __future__ import annotations

import json
from pathlib import Path

from backend.parser import load_json
from backend.validator import validate_all


TURSUN_CONTEXT = (
    "Среди политических соперников Есим-хана источники выделяют султана Турсуна. "
    "В 1613 году правитель Ташкента Турсун восстал против хана Есима, отказался ему подчиняться. "
    "Вскоре султан Турсун провозгласил себя ханом, начал чеканить свои монеты. "
    "Стремление Турсуна к власти, непризнание им хана Есим привело к двоевластию. "
    "Однако Есим относился к этому двоевластию мудро и спокойно. "
    "Но в 1627 году, когда Есим возвращался из похода, разбив ойратов, "
    "Турсун напал на его ставку - Туркестан. "
    "Коварный удар в спину, нанесенный Турсуном, вызвал возмущение среди казахских родов."
)

POEM_CONTEXT = (
    "«Настанет ли день,\n"
    "Когда нам удастся сесть\n"
    "На рыжих, звонко ржащих коней!\n"
    "Взяв в руки звонкое копье,\n"
    "Прижав его к прохладной груди\n"
    "Удастся ли нам преследовать бегущего врага?»."
)


def set_context(item: dict, title: str, context: str) -> None:
    item["context_title"] = title
    item["context"] = context
    item["media"] = []


def main() -> None:
    source_path = Path("19_lunch_openai.json")
    output_path = Path("19_lunch_openai_fixed.json")
    data = json.loads(source_path.read_text(encoding="utf-8"))

    fixed_questions = []
    for item in data["questions"]:
        source_id = item.get("source_item_id")
        if source_id == 220:
            continue
        item = dict(item)
        if 214 <= source_id <= 219:
            set_context(item, "Контекст про Есим-хана и Турсуна", TURSUN_CONTEXT)
        elif 221 <= source_id <= 225:
            set_context(item, "Контекст стихотворения", POEM_CONTEXT)
        else:
            item["context_title"] = ""
            item["context"] = ""
            item["media"] = []
        fixed_questions.append(item)

    data["questions"] = fixed_questions
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    validate_all(load_json(output_path))
    print(f"OK: wrote {len(fixed_questions)} questions to {output_path}")


if __name__ == "__main__":
    main()
