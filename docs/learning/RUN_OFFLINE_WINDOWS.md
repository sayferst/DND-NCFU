# Проверка локального архива на Windows

Для нового CODEX READY и работающей библиотеки используйте
[OPERATIONS.md](OPERATIONS.md). Команда ниже сохраняется как историческая
проверка FIXED(12), а не инструкция включения нового runtime.

Сначала получите изменения ветки setup/development-environment через
`git pull --ff-only`. Если Windows блокирует автоматическую очистку pack-файлов,
используйте `git -c gc.auto=0 -c maintenance.auto=false pull --ff-only`.
Архив остаётся у вас локально, его не нужно коммитить или отправлять в RouterAI.
В корне D:\Projects\DND-NCFU:

```powershell
.\.venv\Scripts\python.exe scripts\learning\import_training_package.py --package "$env:USERPROFILE\Downloads\DND_Training_Package_FIXED (12).zip" --offline --dry-run --resolve-identical-spec-alias --report "..\DND-NCFU-data\learning\audit-01.json"
```

При другом месте ZIP замените путь. Ожидается VERIFIED_DERIVED,19200raw/200alias/
19000canonical и нулевые indexed/SFT-ready. Исходный пакет отмечается неполным
из-за отсутствующей копии master-spec; точный проверенный alias разрешён владельцем.
Проверка не меняет игру/сохранения. Отчёты не перезаписываются: при повторном
запуске укажите новое имя audit-02.json. Для локального карантина можно убрать
--dry-run и добавить --records с путём вне Git, например в DND-NCFU-data\learning.
Это не включит RAG, не создаст предметов и не запустит обучение модели.
