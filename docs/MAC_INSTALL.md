# QuizBot Studio on macOS

## Требования

- **Python 3.11 или 3.12** — `brew install python@3.12` или с https://www.python.org/downloads/macos/
- **Node.js 20 LTS** — `brew install node` или через `nvm` (нужен для сборки веб-интерфейса)
- **ffmpeg** — опционально, только для vision-нормализации изображений: `brew install ffmpeg`

## Перенос проекта на Mac

Вариант A — через GitHub (Telegram-аккаунты подключаются заново в веб-платформе):

```bash
git clone https://github.com/Gumar12/TelegramQuiz.git
cd TelegramQuiz
```

Вариант B — архивом, если нужны существующие сессии и квизы. Скопируйте папку
проекта, исключив непереносимые каталоги:

```bash
rsync -av --exclude='.venv' --exclude='frontend/node_modules' --exclude='frontend/dist' \
  /путь/TelegramQuiz/ /целевой/путь/TelegramQuiz/
```

Так переедут и `data/runtime/accounts/` с сессиями — повторно входить в Telegram не нужно.

## Запуск двойным кликом

1. Откройте файл `scripts/start_quizbot_mac.command`.
2. Если macOS спросит разрешение, подтвердите запуск.

Что делает ярлык:

- создает `.venv`, если его еще нет;
- ставит зависимости из `backend/requirements.txt`;
- создает `backend/.env` из `backend/.env.example`, если его еще нет;
- **собирает веб-интерфейс** (`npm install` + `npm run build`), если `frontend/dist` еще нет;
- освобождает порт `8000`, если он занят;
- запускает `python -m backend.studio_api`;
- открывает `http://127.0.0.1:8000`.

Первый запуск дольше: ставятся Python- и Node-зависимости и собирается фронтенд.

## Telegram и ключи

Telegram-профили (`api_id`, `api_hash`, телефон) создаются в веб-платформе на
странице `Аккаунты`, а не в `.env`. Получить credentials: https://my.telegram.org →
API development tools.

`backend/.env` нужен только для опциональных интеграций (DeepSeek/OpenAI).

## Если macOS блокирует запуск

Права на исполнение:

```bash
cd /path/to/TelegramQuiz
chmod +x scripts/start_quizbot_mac.command
```

Снять карантин Gatekeeper (файл «из непроверенного источника»):

```bash
xattr -d com.apple.quarantine scripts/start_quizbot_mac.command
```

Либо: правый клик по файлу → **Open** → подтвердить один раз.

## Ручная сборка фронтенда (запасной путь)

Если запускаете backend напрямую (`python -m backend.studio_api`), сначала
соберите фронт — иначе на `http://127.0.0.1:8000` будет пусто:

```bash
cd frontend
npm install
npm run build
cd ..
```

`VITE_API_BASE_URL` при боевой сборке не задавайте — фронт обращается к API по
относительному пути на том же порту. `.env.local` нужен только для `npm run dev`.

## Безопасность

Не передавайте чужие `backend/.env` и session-файлы из
`data/runtime/accounts/sessions/` — session равен доступу к Telegram-аккаунту.
