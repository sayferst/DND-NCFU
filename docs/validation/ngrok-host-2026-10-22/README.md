# ngrok вместо неустойчивого Cloudflare — 22.10.2026

Владелец выбрал бесплатный ngrok и предоставил выданный dev-домен. Секреты
в этой проверке не использовались. Никакой публичный endpoint не запускался,
никаких платных запросов, публикации discovery или выпуска допусков не было.

Изменения: owner-only выбор провайдера, DPAPI Authtoken, child-env вместо argv,
ограниченный вывод ошибок агента, очистка при Ctrl+C. Общие подпись/health/build
и восстановление коннектора используются обоими провайдерами. В ngrok-ветке
Cloudflare DNS и7844 не используются. Клиент передаёт
`ngrok-skip-browser-warning: 1` при активации, chat, jobGET и images; health тоже.
Запросы к RouterAI не изменены. Health300с и job polling10с экономят квоту.

Проверки:

- Предварительные затронутые тесты:91passed/9.96с; затем добавлены отдельные
  проверки Qt-запросов Мастера и активации первой установки:19passed/0.22с
  в новом ngrok-наборе. Использованы fake process/opener, временные каталоги,
  Qt offscreen и тестовые строки токенов. Это не живая сеть ngrok.
- Реальный официальный Linux ngrok CLI3.39.12: `version`, `config check` и
  `http --help`. Config v3 с `agent.web_addr: false`, `update_check: false`
  принят. Поддержка `--url`, `--config`, `--inspect=false`, JSON stdout log
  подтверждена. Agent скачан только во временную папку, без автотокена.
- Полная проверка и аудит будут сохранены отдельными raw-файлами рядом.

Полный итог: `scripts/check.py` exit0, **1478passed/223.33с**, безfailed/skipped;
pipcheck/Ruffcheck/format226файлов прошли. Raw: `full-01.txt`. Аудит
`audit-01.json`:75защищённых хэшей неизменны, исходныйпрефиксAGENTS сохранён.
`native-cli-01.txt` фиксирует реальный configcheck, `target-01.txt` —19тестов.

Native Windows, вход в аккаунт ngrok, живой туннель и итоговая Inno-сборка
не проверялись в Linux. Владельцу нужно установить агент, локально ввести
Authtoken, выполнить start и build. Тестировщику нужен только новый Setup.
Успех фальшивых transport-тестов не подтверждает доступность внешней сети.

Официальные источники проверены22.10.2026:

- https://ngrok.com/docs/pricing-limits/free-plan-limits — dev-домен, отсутствие
  session timeout,1ГБ/20000 HTTP/месяц, browser interstitial и bypassheader.
- https://ngrok.com/docs/agent — исходящее TLS443.
- https://ngrok.com/docs/agent/config/v3 — v3agentconfig.
- https://github.com/microsoft/winget-pkgs/tree/master/manifests/n/Ngrok/Ngrok —
  идентификатор установки Ngrok.Ngrok.

Не менялись lockfiles, правила, seeds, промпты, сохранения, бюджеты и версии игры.
