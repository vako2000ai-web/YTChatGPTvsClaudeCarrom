# Carrom AI Showdown — версия 0.2.0

Развитие прототипа из архива 0.1: автоматические матчи, отдельные физика и правила,
покрытие королевы, штрафы/возврат, API JSON Schema, журнал ходов и headless-серии.
Исходники 0.1 сохранены в legacy/v0.1. Это ещё прототип с домашними правилами;
полный турнирный Carrom, Windows exe, replay и запись OBS запланированы в PROJECT_PLAN.md.

## Быстрый запуск на Windows 11

Проверенное окружение: Python 3.14.0 x64, pygame-ce 2.5.8, Pymunk 7.3.0.
pygame-ce предоставляет обычный модуль `pygame`; не ставьте одновременно pygame и pygame-ce.

```powershell
cd C:\Work\YTChatGPTvsClaudeCarrom
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe game.py --mode demo
```

Или запустите Setup.ps1, затем Start.ps1. Скрипты не заменяют существующий .env.
Сразу после запуска матч идёт автоматически. SPACE — пауза после текущего удара,
R — новая серия (при ожидающем API перезапуск заблокирован), ESC — выход.

Demo — две локальные геометрические стратегии, без сети и ключей. Такой матч
нельзя обозначать как реальные решения ChatGPT/Claude. HUD показывает DEMO.

## OpenAI против Claude

Заполните локальный .env, который уже исключён из Git:

```dotenv
MODE=api
OPENAI_API_KEY=ваш_ключ
ANTHROPIC_API_KEY=ваш_ключ
OPENAI_MODEL=точный_доступный_ID
ANTHROPIC_MODEL=точный_доступный_ID
API_TIMEOUT=25
API_MAX_OUTPUT_TOKENS=1024
```

Выберите модели с поддержкой JSON Schema в соответствующих API. ID моделей в
примере намеренно пусты: доступ зависит от аккаунта. При отсутствии ключей/ID
программа завершится с понятной ошибкой до начала матча.

```powershell
.\.venv\Scripts\python.exe game.py --mode api --max-turns 20 --quit-on-finish
```

Это оплачиваемые запросы. До 20 запросов при лимите 20 ходов, один запрос на ход,
SDK retries отключены. Реальных API-матчей при разработке не запускали.
Оба адаптера получают одинаковую инструкцию, полное состояние и ограничения.
Они используют [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
и [Anthropic Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
Неверный JSON/размещение, отказ, timeout или API-ошибка записываются как пропуск
хода, не заменяются demo-ударом. Лимит ходов предотвращает бесконечный матч.
Частые технические пропуски пока не переводят матч в отдельный degraded status;
при анализе обязательно учитывать failures, а не только winner.

## Серии и статистика

```powershell
.\.venv\Scripts\python.exe game.py --mode demo --headless --matches 10 --max-turns 80
.\.venv\Scripts\python.exe game.py --mode demo --matches 3 --quit-on-finish
```

Headless не создаёт окно и считает физику быстрее реального времени. Начинающий
игрок чередуется; цвета пока фиксированы. В matches/ появляются JSONL каждого
матча и JSON/CSV summary серии. GUI серии создают JSONL, summary серии пока
экспортируется только CLI headless. Каталог можно задать через --log-dir.

JSONL содержит `match_start`, `decision_start`, `decision` или `decision_failed`,
`shot_end`, `match_end` либо `match_aborted`. Решение содержит source/model,
параметры удара, публичный комментарий, latency и token usage. Стоимость в деньгах
и сырые HTTP ответы не записываются. Ключи и сообщения исключений SDK не логируются.
Журнал не является покадровым видео или готовым replay-плеером.

## Домашние правила v0.2

- Девять белых у ChatGPT, девять чёрных у Claude, красная королева.
- Своё попадание сохраняет ход; чужая фишка идёт в банк соперника.
- Queen + своя фишка покрывает queen в том же ударе. Иначе нужно покрыть в следующем
  ударе, при неудаче queen возвращается на доску. Queen сама не даёт очков.
- Striker foul возвращает все новые свои фишки и одну старую. Если старой нет,
  образуется долг; будущие свои попадания возвращаются для его погашения.
- Непокрытая queen возвращается при foul. Покрытая queen остаётся в банке.
- Последняя своя фишка возвращается, пока queen не покрыта. После покрытия очистка
  своих девяти фишек выигрывает доску. При лимите ходов — ничья независимо от счёта.
- Ошибка решения API — пропуск без дополнительного striker penalty.
- Возврат фишек автоматический, по свободным местам в центре.

Это не полная реализация официальных правил. Отличия и переход к официальному
ruleset описаны в PROJECT_PLAN.md. Счёт на экране — число удержанных фишек.

## Проверки и запись

```powershell
.\.venv\Scripts\python.exe -m pytest -q
$env:SDL_VIDEODRIVER='dummy'
$env:SDL_AUDIODRIVER='dummy'
.\.venv\Scripts\python.exe game.py --mode demo --frames 30 --screenshot matches\smoke.png
```

После dummy-проверки откройте новый терминал для обычного видимого окна.
Результаты проверки находятся в VALIDATION.md. Тесты не вызывают реальные API.
requirements-tested-win314.txt — полный freeze окружения, на котором проведены проверки;
requirements.txt — диапазоны зависимостей для установки.

Для OBS запустите обычный GUI и добавьте Window Capture окна игры, оставив
видимой метку режима. Автоматическая запись и монтаж CapCut ещё не реализованы.
Перед записью проверить resolution/FPS, читаемость HUD и отсутствие .env на экране.

Структура и правила дальнейшей разработки — AGENTS.md. План — PROJECT_PLAN.md.
