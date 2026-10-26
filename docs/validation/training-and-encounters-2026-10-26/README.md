# Архив FIXED(12) и подключённая схема27 — реальные проверки

До этапа b88df8b, ветка setup/development-environment.

## Данные

Исходный архив4 156 811байт,19членов. Штатный verify_package.py прочитан перед
запуском; raw не менялся. Строгая собственная проверка package-original.json
воспроизводит Missing:DND_Training_Prompt.md; восемь корпусов проходят хеши/счётчики.
Владелец разрешил основной master-spec вместо отсутствующей копии. Отдельный
package-derived.json использует только виртуальный alias с ожидаемым SHA/размером.
Все53раздела перечислены в нём, тексты записей там не публикуются.

Реальные команды:

```text
.venv/bin/python scripts/learning/import_training_package.py --package <исходный ZIP> --offline --dry-run --report <package-original.json>
.venv/bin/python scripts/learning/import_training_package.py --package <исходный ZIP> --offline --resolve-identical-spec-alias --report <package-derived.json> --records <внешний локальный records-01.jsonl>
```

Строгий запуск exit2 (нет дубликата документа); derived exit0.19200структурных
записей,200точных алиасов,19000канонических; approved/indexed/SFT-ready0.
Полный карантин находится вне Git. Это не обучение, не художественный A/B и
не подтверждение достоверности всех математических утверждений источников.

## Игра и инструменты

- target-01.txt:172passed/6failed/15.69с. Шесть synthetic HTTP-тестов model_metrics
  не смогли создать loopback sockets в базовой песочнице (PermissionError).
  Этот прогон не принят. Runtime из-за этого не менялся.
- target-02.txt:178passed/19.35с, тот же набор с разрешением локальных sockets.
- full-01.txt:scripts/check.py exit0,1732passed/229.27с, pip/Ruff check/format272файла.
  Затем найдены UI-цели/восстановление выбора и риск слишком длинной action при
  восьми длинных именах. Первая строка отделена от полного списка имён; добавлен
  реальный максимальный сценарий, а NPC-манёвр/восстановление теперь видны в тексте.
- target-final-01.txt:28passed/2.86с после этих изменений, включая большой состав.
- full-02.txt:окончательный повтор scripts/check.py; точный итог дописан ниже.
- immutable-audit.json:75защищённых файлов,33прежних fixture и6замороженных модулей
  совпадают с b88df8b. Fixture26 выпущен настоящим старым writer через git archive;
  происхождение/SHA/следующий D20(index1/value9) — fixture-v26-source.json.
- code-manifest.json:снимок142исходных/новых тестовых файлов окончательного кода.
- team-battle-qt.png:первичная offscreen-проверка. team-battle-qt-final.png:отдельный
  финальный снимок после исправления целей/выбора. Оба действительно просмотрены.

Qt-сценарий: test_team_encounters.hero(seed13), encounter(first,second;ally friend),
MainWindow с временным SaveSlots, страница героя/бой. English-имена — имена
синтетической fixture. В финальном снимке состав выделен и заблокирован до конца
боя; список атаки содержит действующих противников, не постороннего торговца.

Локальные HTTP-серверы тестовые, без платных/живых запросов к моделям. Новых
зависимостей нет; Windows GUI/PowerShell/Setup, runtime RAG, fine-tuning и качество
прозы после обучения не проверялись. Матрица остатка: ../../learning/IMPLEMENTATION_MATRIX.md.

Отдельный программный сценарий npc-persistence-manual.json: в настоящую Session27
зарегистрирована новая Веста с собственным ID/Definition, затем10обычных часовых
ходов и холодная загрузка. ID сохранился; в отдельном мире второго героя NPC не
появился. Это не человеческая игра и не общий многогеройный world-sharing.

Финальный full-02: scripts/check.py exit0; **1733 passed / 230.85с**. pip check, Ruff check/format272файла успешны. После прогона исходники не менялись. Native Windows/Setup/live API не проверены.
