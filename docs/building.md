# Windows-сборки

Нужны Windows x64, Python 3.12, Git и Inno Setup 6.
Сборщик устанавливает зависимости по хэшам, выполняет тесты, упаковывает PyInstaller,
проверяет состав, self-check и smoke-test EXE, затем запускает Inno Setup.
Ошибка любого этапа останавливает сборку.

Единый установщик с входом admin/tester:

```powershell
.\scripts\build_windows.cmd -Installer -AccountLogin -Profile tester -DiscoveryUrl 'https://raw.githubusercontent.com/sayferst/DND-NCFU/tester-host-address/endpoint.json' -DiscoveryKey '5lGcAqnkdVgVF2TlrY7TRuZyRgvdIQZZ733zsORo6eo='
Copy-Item dist\DND-NCFU-Setup.exe dist\setup.exe
```

DiscoveryKey — открытый ключ проверки подписи. Пароли, API-ключи, bootstrap,
DPAPI-файлы и пользовательские базы не должны попадать в установщик.

CI создаёт один артефакт installer-tester с setup.exe и SHA256. Публикация
выпуска выполняется после успешных проверок; CI сам не сливает PR в main.
Серверный код в server — исходники шлюза, не часть клиентского EXE.
Рабочие BAT владельца и инструменты запуска хоста находятся в ветке разработки.

Без параметра -AccountLogin исходная инфраструктура legacy-профилей сохранена
для совместимости тестов и разработки. Публичный установщик всегда собирается
с -AccountLogin; отдельной личной версии в этом выпуске нет.
