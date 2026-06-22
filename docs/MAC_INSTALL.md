# QuizBot Studio on macOS

Запуск двойным кликом:

1. Распакуйте архив.
2. Откройте файл `scripts/start_quizbot_mac.command`.
3. Если macOS спросит разрешение, подтвердите запуск.

Что делает ярлык:

- создает `.venv`, если его еще нет;
- ставит зависимости из `backend/requirements.txt`;
- создает `backend/.env` из `backend/.env.example`, если его еще нет;
- освобождает порт `8000`, если он занят;
- запускает `python -m backend.studio_api`;
- открывает `http://127.0.0.1:8000`.

Telegram-профили создаются в веб-платформе на странице `Аккаунты`.
`backend/.env` нужен только для опциональных интеграций, например DeepSeek/OpenAI.

Если macOS пишет, что файл нельзя открыть из-за прав:

```bash
cd /path/to/quizbot-studio
chmod +x scripts/start_quizbot_mac.command
```

После этого запускайте `scripts/start_quizbot_mac.command` двойным кликом.

Не передавайте чужие `backend/.env` и session-файлы из `data/runtime/accounts/sessions/`.
