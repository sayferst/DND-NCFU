# Полный автоматический корпус — фактическая проверка

Исходник `0721083`, чистая ветка feature/unified-rpg-automatic-gm до изменения.
Предыдущее свидетельство baseline:1882passed,docs/unified/validation/full-check-09.txt.
Задание владельца: автоматический доступ ко всем 19000фрагментам,без импортаUI.

Итоговая команда `.venv/bin/python scripts/check.py`: **1894passed/303.49с**,
pipcheck/Ruffcheck/format330файлов успешны,exit0:full-02.txt.
После этого код/база не менялись. code-manifest-01 фиксирует SHA исходников
и готового артефакта. immutable-01:86защищённых файлов иAGENTS неизменны.
secret-scan-01не нашёл секретов в новых/изменённых текстах.

Подготовка: `python -m training.build_corpus_knowledge --input SOURCE.zip
--output NEW_DIRECTORY`. preparation-02.json содержит конечный manifest:
19000канонических карточек/200алиасов,исходныйSHA f1a7568e…8146fe,
готоваяSQLite SHA252f3d68abffcee4c612c6943ad3528fd012413559c400942d3646309abb65aa.
Полные исходные документы вGit/бинарник не добавлены;база содержит описательные
проекции с sourceSHA/строками. Ни humanreview,ни SFTapproval не приписываются.

Сохранены отдельные попытки:

- target-01:14passed/0.90с.
- target-02:131passed/51.64с — новыйкорпус,старыйlearning,реальныеUI/transport/
  packagedprobe/objectdescriptions/созданиeмира.
- target-03:1failed/11passed,новыйтестошибочносклеилtitle иexcerpt без пробела
  и искал несуществующий токенLOМесто;исправлено построение тестового запроса.
- target-04:12passed/0.82с,реальныйFTS-matchкаждогоиз19000rowid.
- full-01:1894passed/303.90с,pip/Ruff330файлов успешны.
- Затем улучшена проекцияv2:1700карточек получили ранее пропущенные допустимые
  описательныеполя;заглушек только с названием0. Добавлены обычные падежные
  формы для поиска;проверено«говорю с пекарем».
- target-05:14passed/1.31с;после этого full-02прошёл целиком.

Проверяется неCOUNTвнешнейcontent-таблицы,а настоящий tokenMATCHпо каждому
rowid. Проверены конец каждого из семи каноническихисточников,200алиасов,
естественныйпоиск,ограничениеUTF-8,три фактическихpayload(genesis/planner/writer),
фильтрыhidden/numeric/injection,read-only,повреждение/отсутствие/безFTS5,
неизменность Session/RNG.

build-02,self-check-02,smoke-02успешны. ВнастоящемLinuxPyInstaller:
automatic_corpus.status=ready,records=19000,aliases=200,тотжeSHA.
JSON/SQLite/RNG/worldcreation проверены;external_model_requests=0.
packaging-01:307файлов,manifest+SQLite включены,raw/Torch/weights/training
в пакете не обнаружены. Provenanceбинарника0721083-modified:сборкадоcommit.
ЭтоLinuxbundle;nativeWindows/DPI/Setup здесь не проверены.

retrieval-audit-02:все19000карточек проходят проверку читателя и вмещаются
в бюджет;максимальнаяоднасправка1085байтприобщемлимите2400.
База30146560байт.80поисковыхзапросов:медиана1.18мс,p95 10.12мс,
первыйпоиск23.74мс. ЭтоизмерениеэтойLinux-среды,не скорости ПКвладельца.
ИзолированныйPython-процесс:peakRSS16976КиБ;это неRAMвсейQt-игры.
Модель не вызывалась,художественныйприрост не измерен,веса не обучались.

build-01/self-check-01/smoke-01/retrieval-audit-01относятся к первой проекцииv1,
с прежнимSHA94d59568…16c54c;они сохранены как история,не перезаписаны.
