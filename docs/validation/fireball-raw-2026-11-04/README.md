# Raw FIREBALL, полный проход 04.11.2026

`raw-stream-report.json`: все7699684480байт официального архива, SHA256
787796a8d88c770ea08be886121fe87d116c2efbbe06ee175a93ddd912ca1226.
Внешний и внутренние gzipCRC прошли;39448members/12660667строк,0ошибок разбора.
Сетевой EOF первого прохода устранён повтором;39267members проверены поSHA
без повторного увеличения счётчика. Это не partial/archive-trailer warning.

`coverage-by-source.json`:24748raw-файлов/12506838событий и14700native-filtered
файлов/153829ходов. Эти строки/ссылки не являются столькими независимыми партиями.
`all-members.csv.gz`:каждыйmember, размер, SHA, строки, parsing и цепочкаSHAстрок.
Индекс всех позиций и полный reference-ledger вне Git, текстовые raw-поля
не копировались целиком из-за диска. Это COMPLETE_AUDIT/INDEX, не полный B-дамп.

`native-reference-report.json`:1375526подтверждённых ссылок и10недоступных
индексов.32974after-ссылки author_bot=False,28446роль неизвестна.
DM и человеческое авторство текста не выводятся из account flag.
Все153829HF-записей однозначно сопоставлены по полному нормализованному core
и точному вектору ссылок;68кандидатов отброшены, неоднозначных групп0.
Корреспонденция не объявляется byte-идентичностью разныхJSON-сериализаций.

`native-hf-group-validation.json`:HF-файлы —1471пакет14700боёв
(1469×10+9+1), а не1471бой. Междустарымиsplits native-бои не пересекаются.
Кампании полностью не восстановлены.

`legacy-history-audit.json`:старыйконтекстмешалбои21946раз в12514views.
`history-correction-manifest.json`:12514пересчитанныхinput/token metadata;
1800безпредысториисохраненынаблюдениями,10714имеюттолькосвойконтекст.
`history-correction-verification.json`:все12514проверены официальным
AutoTokenizer, targets неизменны,0межбоевых/неразрешённыхhistory-связей;
новыесвязи — подмножество прежнихпроверенныхпорядков, token_delta−1229742.
База и старыйZIP не перезаписаны. Новый материализатор требует overlay для
legacy-coverage; новый builder не принимает соседство в HF-файле за одну историю.

`targeted-final-87.txt`:87passed/5.54с. Команда:

```text
.venv/bin/python -m pytest tests/test_fireball_raw.py tests/test_fireball_observations.py tests/test_fireball.py tests/test_training_tokenization.py tests/test_faun_tokenizer_fetch.py tests/test_faun_transfer.py tests/test_training_pipeline.py tests/test_training_story_contract.py tests/test_training_pack_review.py -q
```

Ruff463файла успешны. Новый Windows/GUI/GPU/обучение/оценка качества
рассказчика не запускались. Все admission/human_approved/training_steps0.
Источник/лицензии/команды и ограничения:
[FIREBALL_RAW.md](../../intelligent_gm/FIREBALL_RAW.md).
