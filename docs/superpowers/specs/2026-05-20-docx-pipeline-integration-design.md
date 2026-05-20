# DOCX Pipeline Integration Design

**Date:** 2026-05-20
**Status:** Approved for planning
**Scope:** Integrate the useful MVP archive pipeline into the existing Quizbot project without replacing the current Telethon uploader.

## Goal

Add a first pipeline stage that converts a DOCX file of Kazakhstan history question-answer rows into the JSON format already consumed by the current uploader:

```json
[
  {
    "question": "Question text",
    "options": ["A", "B", "C", "D"],
    "correct": 2,
    "explanation": ""
  }
]
```

The source archive `quizbot_pipeline_mvp.zip` already proves the conversion approach on a 299-row DOCX. This project should reuse that logic, but the canonical runtime format remains the existing top-level JSON array expected by `parser.py`, `models.py`, `validator.py`, and `main.py`.

## Non-Goals

- Do not replace the existing Telethon uploader with `upload_to_quizbot_skeleton.py`.
- Do not add GPT-generated distractors in this phase.
- Do not automatically upload all 299 questions as one quiz. The current validator caps a single quiz at 100 questions for account-safety reasons.
- Do not modify Telegram credentials, session handling, or @QuizBot flow behavior.
- Do not rewrite unrelated README encoding or existing user edits.

## Approach

Use approach 1: integrate the archive's DOCX-to-JSON stage into the current project.

Add a script named `docx_to_quiz_json.py` at the project root. It should read `.docx` paragraphs formatted as:

```text
1. Question text <em dash> Correct answer
1. Question text <en dash> Correct answer
1. Question text - Correct answer
```

The actual implementation should support the dash variants already used in the archive script: em dash, en dash, and hyphen surrounded by spaces.

The script will extract `number`, `question`, and `answer`, generate three distractors from other answers in the same rough category, shuffle the four options with a deterministic seed, and write uploader-ready JSON.

## Components

`docx_to_quiz_json.py`

- Owns DOCX parsing, question-answer splitting, distractor selection, option shuffling, and JSON writing.
- Depends on `python-docx` and standard library modules.
- Does not import Telethon or contact Telegram.

`models.py` and `validator.py`

- Remain the source of truth for uploader input validation.
- The generated compact JSON must pass these validators.

`requirements.txt`

- Add `python-docx` because conversion is now part of the project.

`questions.example.json`

- May remain the small hand-written example. Generated real `questions.json` stays ignored by git.

## Output Modes

The default output mode should be the compact uploader format:

```json
[
  {
    "question": "Правильный вариант периодизации каменного века",
    "options": [
      "Эпоха саков",
      "Палеолит - мезолит - неолит - энеолит",
      "Асан Кайгы",
      "Эпоха просвещения"
    ],
    "correct": 2,
    "explanation": ""
  }
]
```

For archive compatibility, an optional `--extended` flag may write the archive-style object:

```json
{
  "quiz_title": "История Казахстана",
  "quiz_description": "Тест по истории Казахстана",
  "questions_count": 299,
  "questions": []
}
```

The compact mode is required. The extended mode is optional and should not block implementation if it adds friction.

## CLI

Required command:

```bash
python docx_to_quiz_json.py --input 11111_dedup.docx --output questions.json --seed 42
```

Optional metadata flags:

```bash
python docx_to_quiz_json.py --input 11111_dedup.docx --output questions.extended.json --title "История Казахстана" --description "Тест по истории Казахстана" --extended
```

Recommended upload command after conversion:

```bash
python main.py --file questions.json --name "История Казахстана"
```

If the generated file has more than 100 questions, `main.py` should continue to fail through the existing validator. Splitting large generated files is a separate phase.

## Data Flow

1. User provides a DOCX file with one question-answer pair per paragraph.
2. `docx_to_quiz_json.py` normalizes whitespace and parses rows matching `number. question - answer`.
3. The script classifies each item as date, person, place/state, term, period, or general.
4. Distractors are selected from answers in the same category, falling back to all answers if a category is too small.
5. The correct answer plus three distractors are shuffled using the configured seed.
6. The script writes UTF-8 JSON with `ensure_ascii=False`.
7. Existing `parser.py`, `models.py`, and `validator.py` validate the result before upload.

## Error Handling

- Missing input file: fail with a clear CLI error.
- DOCX with no parseable rows: fail and show the expected row format.
- Fewer than three valid distractors: fill from deterministic generic fallback values, then validate the final options.
- Duplicate options after normalization: reject the question or replace the duplicate from fallback candidates before writing.
- Invalid generated question according to `Question`: fail before writing a misleading output file.

## Testing

Use lightweight local verification:

- Run the converter against `11111_dedup.docx`.
- Confirm the generated JSON parses with `parser.load_json`.
- Confirm `validate_all` passes for a small sliced sample of 3-5 questions.
- Confirm the full 299-question file intentionally trips the existing `>100` validator if loaded for upload as one quiz.
- Keep Telegram smoke testing manual and separate: upload only 3-5 questions first.

## Implementation Boundaries

The implementation should avoid touching the current uploader flow unless a direct compatibility issue appears. The existing uncommitted changes in `main.py` and `quizbot_client.py` are outside this design and should be preserved.
