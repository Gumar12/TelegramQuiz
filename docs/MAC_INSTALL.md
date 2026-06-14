# QuizBot Studio on macOS

Запуск двойным кликом:

1. Распакуйте архив.
2. Откройте файл `scripts/start_quizbot_mac.command`.
3. Если macOS спросит разрешение, подтвердите запуск.

Что делает ярлык:

- создает `.venv`, если его еще нет;
- ставит зависимости из `backend/requirements.txt`;
- создает `backend/.env` из `backend/.env.example`, если его еще нет;
- открывает `backend/.env` для заполнения;
- освобождает порт `8000`, если он занят;
- запускает `python -m backend.studio_api`;
- открывает `http://127.0.0.1:8000`.

Если macOS пишет, что файл нельзя открыть из-за прав:

```bash
cd /path/to/quizbot-studio
chmod +x scripts/start_quizbot_mac.command
```

После этого запускайте `scripts/start_quizbot_mac.command` двойным кликом.

Не передавайте чужие `backend/.env` и `data/runtime/quizbot_session.session`.
