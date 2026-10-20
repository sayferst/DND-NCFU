# Аудит Windows-приложения — 20.10.2026

Исходный коммит355d8da, веткаsetup/development-environment, рабочее дерево чистое.
Задание получено в file_00000000f9bc81f48b484156b5ac8bb7 и прочитано полностью.
Система упаковки существует: PyInstaller6.16.0, onedir/windowed, отдельный hash-lock,
скрипт PowerShell, _MEIPASS, внешний LOCALAPPDATA и пользовательский local.txt.

Найдено:
- скрипт не проверяет Python/архитектуру, не ставит lock, не запускает готовыйEXE,
  не делает ZIP/инвентаризацию, не изолирует старый build;
- self-check использует assert и охватывает лишь три справочника/фон;
- ресурсы включаются каталогами целиком; нет явного полного перечня;
- у главного окна старое название прототипа; нет ICO/версииPE;
- нет безопасного startup crash-report без консоли;
- нет nativeWindowsworkflow/установщика;
- новые public-descriptions уже попадают через каталог, но отдельно не проверяются;
- данные/ключи уже внеEXE, формат сохранений менять не требуется;
- Qt/shiboken wheels не содержат отдельных license-файлов; нужна дополнительная
  проверка уведомлений и официальных текстов, не заявление о юридическойготовности.

Среда Linux, PyInstaller доступен; pwsh/Windows отсутствуют. gh REST и GraphQL
возвращаютForbidden, nativeWindowsrunner из этойсессии не запущен. Это не
автоматический отказ безопасности, а недоступностьAPI. Git push работает.
Разрешённые версионные ссылки Actions проверены git ls-remote:
checkout/v5=fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09;
setup-python/v6=ece7cb06caefa5fff74198d8649806c4678c61a1;
upload-artifact/v4=ea165f8d65b6e75b540449e92b4886f43607fa02.
Qt LGPL3 получен из официального qt/qtbase tagv6.10.1 (raw.githubusercontent.com).
Платные модели не вызывались. Ключи/кампании/fixture не изменяются.
