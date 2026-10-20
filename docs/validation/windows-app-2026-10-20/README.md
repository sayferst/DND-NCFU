# Проверки 1X — 20.10.2026

База355d8da. Отдельные коммиты: f9bb78a аудит,51ddf0a запуск,34eec5b упаковка.
Полный результат на34eec5b: **1192passed/138.82с**,0failed/skipped,
pip/Ruffcheck/formatуспешны,182Python-файла (`full-final.txt`).

Свидетельства:

- `AUDIT.md` — точки интеграции, API403 и отсутствиеWindows;
- `stage-runtime.txt` — исходные3сбоя старых тестовыхargv/синхронного запуска;
- `stage-runtime-02.txt` —52passed/6.70с после адаптацииlauncher-проб;
- `stage-packaging.txt` —27passed/6.56с, втомчисле ZIPна синтетическихPE;
- `source-self-check.txt`, `source-smoke.txt` — ранние исходные пробы. Враннем
  sourceSmoke network_requests0 относится кselfcheck; полный итог имеет2loopback,
  исправленное полеnetwork_requests=2 в позднем frozenотчёте ниже;
- `linux-build-01.txt` — обнаружен NameErrorWORKPATH вspec;
- `linux-build-02.txt` — сборкауспешна, но `linux-frozen-smoke.*` показывает
  AttributeError для builtin_sqlite3 без__file__; это не ошибка игры/RouterAI;
- `linux-build-03.txt` — успешная новаясборка послеисправления;
- `linux-frozen-self-check-02.*`, `linux-frozen-smoke-test-02.*` — **обауспешны**
  после копирования в `/tmp/Перенос игры 1X окончательный/DND-NCFU`, запуск из
  `/tmp/dnd-1x-launch-away-02`, PATH=/usr/bin:/bin, безPYTHONPATH/PYTHONHOME,
  RPG_VKR_DATA_DIR=/tmp/dnd-1x-external-data-02. Расположениезависимостей проверено,
  JSON/SQLite/RNG/кэш/refs/GUI/TLS работают,2локальныхPOST,0внешнихмоделей;
- `linux-frozen-manifest.json` —287файлов/255361071байт, проверены ресурсныйсписок,
  лицензии и отсутствие пользовательскихфайлов/подозрительныхключевыхстрок;
- `loading-preview.png` — просмотренныйQtснимок. Двакадра через200мсразличаются,
  значениепрогресса60остаётся60; послеcloseтаймеростановлен;
- `immutable-audit.json` —75исходныхфайлов побайтноравны355d8da,
  AGENTSсохраняет прежнийпрефикс.

Linuxпакет не включён вGit, не названWindowsZIP. Егоразмер не предсказывает размер
Windowsпоставки. Windows/PowerShell/Inno/настоящийDPAPI/чистыйПКбезPython/
DPI/настоящаяRouterAIгенерация здесь не проверены. Windowsархиватор требует
Windowsfrozenотчётс nativeDPAPI; Linuxрезультаты его не заменяют.
GitHubAPI403, Actionsневызывался; workflowпока врабочейветке, дляручнойкнопки
GitHubтребует наличиеworkflowвmain. [Инструкция](../../WINDOWS_APP.md).
