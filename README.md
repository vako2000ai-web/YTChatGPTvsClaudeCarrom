# Carrom AI Showdown — версия 0.3.2

Правила одиночной игры ICF, автоматический матч, покадровый replay, OBS WebSocket v5
и Windows EXE. Цифровые адаптации: `RULES_COVERAGE.md`; результаты проверок:
`RELEASE_REPORT.md`; готовая сборка: `WINDOWS.md`.

```powershell
.\Setup.ps1
.\.venv\Scripts\python.exe game.py --mode demo --official-match
.\.venv\Scripts\python.exe game.py --mode demo --headless --official-match --report matches\result.json
.\.venv\Scripts\python.exe game.py --mode api --official-match
.\.venv\Scripts\python.exe game.py --replay matches\example.replay.jsonl.gz
.\.venv\Scripts\python.exe game.py --replay-info matches\example.replay.jsonl.gz --report matches\info.json
.\.venv\Scripts\python.exe game.py --mode demo --official-match --obs-record --obs-setup-scene --obs-output-dir recordings
.\BuildWindows.ps1
```

`--rules icf` выбран по умолчанию; `--rules aicf-senior` задаёт 10 секунд;
`--rules house` включает сохранённые домашние правила v0.2.
`--official-match` — серия игр до двух побед, иначе запускается один борд.
`--round-stage quarter` меняет условие смены сторон третьей игры;
`--toss-seed` позволяет повторить жеребьёвку дополнительного борда.
Технический лимит ходов не присуждает победу в официальном профиле.

Ключи API и пароль OBS — в `.env`, в архиве только `.env.example`.
`--config` позволяет выбрать другой локальный `.env`. Replay не требует ключей
даже при `MODE=api` в конфигурации. Кадры сохраняют фишки, страйкер и правила;
воспроизведение не рассчитывает удары заново. SPACE/стрелки/HOME/END — управление.
Таймлайн показывает физику и прицеливание; ожидание API и паузы между бордами пропускаются.
OBS должен работать с WebSocket v5. Создаётся сцена окна Carrom; после записи
восстанавливаются сцена, каталог и mute глобальных аудиоисточников.
Для звука создаётся Application Audio Capture процесса игры. Микрофон и общий
звук компьютера временно выключаются, чтобы избежать постороннего звука и удвоения.
`--self-test --report check.json` проверяет реальный код SDK через локальный HTTP
MockTransport без расходов и сетевых вызовов.

## Прицеливание и оформление v0.3.1

Перед каждым ударом биток стоит на выбранной ИИ позиции с прицельной линией
2 секунды. `--aim-seconds 1/2/3` задаёт длительность; линия отражает выбранный угол,
не гарантирует дальнейший путь фишек. В официальном GUI время подготовки
резервируется из дедлайна. Headless не делает визуальную паузу.

Фишки рисуются со сглаживанием, бликом и мягкой тенью. Девять PNG-оформлений
ImageGen находятся в `assets/boards`, точные промпты — `generation-prompts.json`.
Новая доска, включая R, получает случайный дизайн без немедленного повтора.
Дизайн не меняет правила/физику. Replay сохраняет выбранную тему и время прицеливания;
старые replay открываются с классическим оформлением. Ожидание API и межбордовые
паузы всё ещё не включены в replay, его время не равно времени видео OBS.

По умолчанию праздничные темы доступны вместе с обычными в сезон:
Halloween 1 октября–2 ноября, Новый год 20 декабря–10 января,
Рождество 15 декабря–7 января. Это художественные сезонные окна, не календарь выходных.
Все варианты доступны через `--board-season all`; конкретная тема — `--board-theme`.

```powershell
.\.venv\Scripts\python.exe game.py --mode demo --board-season all --aim-seconds 3
.\.venv\Scripts\python.exe game.py --mode demo --board-theme halloween
.\.venv\Scripts\python.exe game.py --mode demo --board-theme new_year
.\.venv\Scripts\python.exe game.py --mode demo --board-theme christmas
```

Актуальная сверка концепции — `CONCEPT_REVIEW.md`; план — `PROJECT_PLAN.md`;
результаты новых проверок — `RELEASE_REPORT-v0.3.1.md`.


## Звук, комментарии и монтажные материалы — v0.3.2 / этап 0.7

- Оригинальные звуки удара, столкновения, борта, лузы, фола, королевы и завершения.
  События наблюдают физику, не изменяя решения/скорости. M — mute, −/+ — общая громкость.
  Отдельные уровни SFX/music/voice — в `.env.example`. Музыка выключена по умолчанию.
- Два виртуальных комментатора используют авторские шаблоны по завершённым ударам.
  Реплики в HUD и SRT помечены авторскими; публичные комментарии игроков отдельны.
- Рядом с каждым журналом создаётся `<имя>.media`: `events.jsonl`, `manifest.json`,
  `player.srt`, `commentator.srt`, `voice.srt`, `sfx.wav`, `voice-1.wav`, `voice-2.wav`,
  `CAPCUT.txt`. WAV — mono PCM16 / 24 kHz. Пустые голосовые дорожки содержат тишину.
- GUI сохраняет монотонное время с ожиданием API. Headless использует время симуляции.
  Replay воспроизводит сохранённые SFX и авторский текст из соседней `.media`, без API;
  озвучку для монтажа берите из WAV/SRT живой записи. Старые replay могут быть без звука.
- У OBS отдельный источник `Carrom AI Showdown / Game Audio`, маршрутизация на 1/2.
  Выбор записываемых дорожек задаётся профилем OBS: настройка маршрутизации сама по себе
  не включает дорожку 2 в файл. WAV экспортируется отдельно независимо от этого выбора.
  `video_offset` в manifest — оценка сдвига относительно подтверждения StartRecord.
  Сверьте её по первому удару; после нарезки SRT необходимо пересчитать.
- WAV-стемы используют уровень громкости на старте каждого клипа. Изменение громкости
  внутри уже играющей реплики не пересчитывает этот стем; OBS сохраняет реальный звук.
  Музыкальный цикл отдельно доступен в `assets/audio/music.wav` и в стемы не включается.
- При отключённом микшере текст/SRT работают, платная озвучка не стартует. `--no-audio`
  отключает звук/озвучку, даже если ElevenLabs включён в `.env`. Headless/replay не вызывают TTS.

### Опциональная платная озвучка ElevenLabs

Заполните в локальном `.env`: `ELEVENLABS_API_KEY`, два разных `ELEVENLABS_VOICE_ID_1/2`,
`ELEVENLABS_ENABLED=true`, консервативную цену своего тарифа
`ELEVENLABS_USD_PER_1000_CHARACTERS` и пределы символов/оценки USD. Цена по умолчанию 0
запрещает включение: стоимость своего тарифа задаёт пользователь, она не угадывается.
Модель по умолчанию `eleven_multilingual_v2`, endpoint with-timestamps, PCM 24000 → WAV.
Кеш WAV и alignment — `matches/.voice-cache`. Постоянный SQLite-счётчик резервирует
символы и оценку до запроса, включая неуспешные запросы. Счёт провайдера окончательный;
внутренняя оценка не гарантирует денежный предел при неверно заданном тарифе.
Лимиты общие для запусков с тем же log-dir; повышайте их только осознанно.

Озвучка выполняется фоновым потоком, не задерживает API/физику. Очередь ограничена,
устаревшие более чем на 15 секунд реплики пропускаются, текст остаётся. При выходе
очередь отменяется; уже отправленный запрос может завершить запись кеша. Voice SRT
начинается в момент фактического проигрывания WAV, а не отправки запроса.
Выбирайте голоса с правом использования для своего канала. В сборке нет чужих голосов.
Оригинальные звуки/музыкальный цикл — CC0, подробности `assets/audio/LICENSE.txt`.

```powershell
.\.venv\Scripts\python.exe game.py --mode demo
.\.venv\Scripts\python.exe game.py --mode demo --no-audio
.\.venv\Scripts\python.exe game.py --mode demo --obs-record --obs-setup-scene --obs-output-dir recordings
```

OpenAI API key можно создать без Plus, но стандартные API-запросы оплачиваются
отдельно от подписки. Игра использует API-ключи; Sign in with ChatGPT пока не подключён.

## Историческая документация v0.2

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


## Проверка Anthropic API отдельным скриптом

Из папки `Keys`: `..\.venv\Scripts\python.exe .\TestAPI.py --dry-run` проверяет
корневой `.env` без сети. Без `--dry-run` отправляется ровно один платный Messages
запрос с retries=0. `--model` переопределяет модель только для этого запуска.
Скрипт не проверяет доступность модели/баланс в dry-run.

При HTTP 400 показывается безопасная подсказка для известных формулировок
ошибок баланса, лимита расходов, модели и параметров. Неизвестная причина явно
обозначается нераспознанной: код 400 сам по себе недостаточен для диагноза.
Сырые сообщения API, ключи и HTTP-заголовки не выводятся. Проверки этого скрипта:
`.\.venv\Scripts\python.exe -m pytest -q tests/test_key_script.py` (без сети).
