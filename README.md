# Skrudj — барахолка WhiteBelStudio

Skrudj — приложение для работы с объявлениями через Telegram и планируемую интеграцию VK. Код развивается по этапам; возможности считаются готовыми только после проверок.

## Требования

- Python 3.12 или новее в пределах поддерживаемых зависимостями версий.
- Git.
- Токен Telegram-бота для запуска Telegram-интерфейса.

## Локальный запуск

### Windows (PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
Copy-Item .env.example .env
```

### Linux / macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cp .env.example .env
```

Откройте файл .env и задайте TELEGRAM_BOT_TOKEN. Локальная база SQLite по умолчанию создаётся в data/skrudj.sqlite3; для другого окружения задайте DATABASE_URL. Настройки администратора указываются в TELEGRAM_ADMIN_IDS через запятую.

Запуск:

```bash
python -m skrudj
```

Если токен Telegram не задан, приложение инициализирует базу данных и завершится без запуска polling. Это позволяет проверить конфигурацию и создание базы, но не является проверкой работающего бота.

## Проверки качества

```bash
ruff check src tests
pytest
```

GitHub Actions автоматически выполняет Ruff и pytest при push в main и при pull request в main.

## Документация

- Архитектура: docs/ARCHITECTURE.md
- Дорожная карта: docs/ROADMAP.md
- Переменные окружения: .env.example

## Безопасность

- Реальные токены и пароли нельзя коммитить; храните их только в локальном .env или секретах окружения.
- .env и локальные базы данных исключены из Git через .gitignore.
- Рассылки по умолчанию находятся в режиме dry-run; не включайте реальные отправки до завершения соответствующего этапа и проверки ограничений платформ.
