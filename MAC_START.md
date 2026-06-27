# 🚀 Запуск QuizBot на Mac — начни отсюда

## 1. Установи нужные инструменты

Открой **Терминал** (Spotlight → «Terminal»).

**a) Homebrew** (менеджер программ, если ещё не стоит):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**b) Python и Node.js** (обязательны):
```bash
brew install python@3.12 node
```

**c) ffmpeg** (необязательно — только для AI-обработки картинок):
```bash
brew install ffmpeg
```

Проверь, что всё встало (нужны Python ≥ 3.11 и Node ≥ 18):
```bash
python3 --version
node --version
```

### Что и зачем нужно

| Инструмент   | Зачем                                    | Обязательно |
|--------------|------------------------------------------|-------------|
| Homebrew     | устанавливает остальное                  | да*         |
| Python 3.12  | backend (сервер, заливка в Telegram)     | да          |
| Node.js 20   | сборка веб-интерфейса                     | да          |
| ffmpeg       | сжатие изображений для AI-нормализации    | нет         |

\* Homebrew нужен, только чтобы поставить Python и Node. Если они уже есть — пропусти.

## 2. Запусти приложение

Распакуй архив, затем в Терминале перейди в папку проекта и разреши запуск скрипта:
```bash
cd ~/Downloads/TelegramQuiz      # путь, куда распаковал
chmod +x scripts/start_quizbot_mac.command
```

Дальше дважды кликни в Finder по **`scripts/start_quizbot_mac.command`**.

Скрипт сам: создаст окружение, установит зависимости, **соберёт веб-интерфейс**,
запустит сервер и откроет браузер на `http://127.0.0.1:8000`.
Первый запуск занимает несколько минут.

> Если macOS блокирует файл («из непроверенного источника»): правый клик по нему →
> **Open** → подтвердить. Или сними карантин:
> ```bash
> xattr -d com.apple.quarantine scripts/start_quizbot_mac.command
> ```

## 3. Подключи Telegram

1. Получи `api_id` и `api_hash`: https://my.telegram.org → войти по номеру →
   **API development tools** → создать приложение.
2. В открывшемся приложении зайди в раздел **«Аккаунты»** → создай профиль →
   введи `api_id`, `api_hash`, телефон → подтверди кодом из Telegram.

Готово. Дальше — просто двойной клик по `start_quizbot_mac.command`.

---

Подробная инструкция (перенос данных, устранение проблем): **`docs/MAC_INSTALL.md`**.
