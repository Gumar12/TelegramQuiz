# Сделать пресет `fast` чуть медленнее (Mac)

Инструкция для Mac (Terminal / zsh). Делает заливку в `fast` чуть медленнее и
безопаснее для живого аккаунта.

## 1. Перейти в папку проекта

```bash
cd ~/путь/к/Quizbot
```

(укажи свой путь до папки, где лежит `backend`)

## 2. Применить одной командой

```bash
python3 -c 'import pathlib; p=pathlib.Path("backend/config.py"); s=p.read_text(encoding="utf-8"); old="""    "fast": {\n        "DELAY_BETWEEN_MESSAGES": (1.0, 2.0),\n        "DELAY_BETWEEN_QUESTIONS": (3.0, 6.0),\n        "LONG_PAUSE_EVERY_N_QUESTIONS": 10,\n        "LONG_PAUSE_DURATION": (15.0, 25.0),\n    },"""; new="""    "fast": {\n        "DELAY_BETWEEN_MESSAGES": (1.5, 3.0),\n        "DELAY_BETWEEN_QUESTIONS": (5.0, 10.0),\n        "LONG_PAUSE_EVERY_N_QUESTIONS": 10,\n        "LONG_PAUSE_DURATION": (20.0, 35.0),\n    },"""; t=s.replace(old,new); p.write_text(t,encoding="utf-8"); print("fast preset updated" if t!=s else "pattern not found")'
```

Должно вывести `fast preset updated`.
Если вывело `pattern not found` — значит блок `fast` уже изменён или отличается
от исходного, правь вручную в `backend/config.py`.

## Что меняется

| Параметр | Было | Стало |
|---|---|---|
| Пауза между сообщениями | 1–2 сек | 1.5–3 сек |
| Пауза между вопросами | 3–6 сек | 5–10 сек |
| Длинная пауза | 15–25 сек | 20–35 сек |

## 3. Запуск заливки

```bash
python3 -m backend.main --speed fast
```
