# Настройка скорости пресета `fast`

Пресет `fast` управляет паузами при заливке вопросов в QuizBot. Значения задаются
в `backend/config.py` → `SPEED_PRESETS["fast"]`. Меньше значения = быстрее,
больше = медленнее и безопаснее для живого аккаунта.

## Текущие значения (чуть медленнее / безопаснее)

| Параметр | Было | Стало |
|---|---|---|
| Пауза между сообщениями | 1–2 сек | 1.5–3 сек |
| Пауза между вопросами | 3–6 сек | 5–10 сек |
| Длинная пауза | 15–25 сек | 20–35 сек |
| Длинная пауза каждые | 10 вопросов | 10 (без изменений) |

## Применить одной командой

Запускать **из корня проекта** (там, где лежит папка `backend`). Команда
безопасно заменяет блок `fast` целиком — простой replace по значениям рискован,
т.к. кортеж `(3.0, 6.0)` встречается в файле несколько раз.

```bash
python -c 'import pathlib; p=pathlib.Path("backend/config.py"); s=p.read_text(encoding="utf-8"); old="""    "fast": {\n        "DELAY_BETWEEN_MESSAGES": (1.0, 2.0),\n        "DELAY_BETWEEN_QUESTIONS": (3.0, 6.0),\n        "LONG_PAUSE_EVERY_N_QUESTIONS": 10,\n        "LONG_PAUSE_DURATION": (15.0, 25.0),\n    },"""; new="""    "fast": {\n        "DELAY_BETWEEN_MESSAGES": (1.5, 3.0),\n        "DELAY_BETWEEN_QUESTIONS": (5.0, 10.0),\n        "LONG_PAUSE_EVERY_N_QUESTIONS": 10,\n        "LONG_PAUSE_DURATION": (20.0, 35.0),\n    },"""; t=s.replace(old,new); p.write_text(t,encoding="utf-8"); print("fast preset updated" if t!=s else "pattern not found")'
```

### Для Mac (Terminal / zsh)

На Mac используйте `python3`. Запускать из корня проекта:

```bash
python3 -c 'import pathlib; p=pathlib.Path("backend/config.py"); s=p.read_text(encoding="utf-8"); old="""    "fast": {\n        "DELAY_BETWEEN_MESSAGES": (1.0, 2.0),\n        "DELAY_BETWEEN_QUESTIONS": (3.0, 6.0),\n        "LONG_PAUSE_EVERY_N_QUESTIONS": 10,\n        "LONG_PAUSE_DURATION": (15.0, 25.0),\n    },"""; new="""    "fast": {\n        "DELAY_BETWEEN_MESSAGES": (1.5, 3.0),\n        "DELAY_BETWEEN_QUESTIONS": (5.0, 10.0),\n        "LONG_PAUSE_EVERY_N_QUESTIONS": 10,\n        "LONG_PAUSE_DURATION": (20.0, 35.0),\n    },"""; t=s.replace(old,new); p.write_text(t,encoding="utf-8"); print("fast preset updated" if t!=s else "pattern not found")'
```

Если перед этим переходите в папку проекта:

```bash
cd ~/путь/к/Quizbot
```

### Примечания

- Работает в **PowerShell, Git Bash и на Mac/Linux**. В обычном **cmd.exe**
  одинарные кавычки не сработают — используйте PowerShell.
- Печатает `fast preset updated` при успехе. `pattern not found` означает, что
  блок `fast` уже изменён или отличается от исходного — тогда правьте вручную.
- Если `python` не находится: `py -c '...'` (Windows) или `python3 -c '...'`
  (Mac/Linux).

## Запуск заливки в этом режиме

```bash
python -m backend.main --speed fast
```
