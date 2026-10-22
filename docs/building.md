# Windows-сборки

Нужны Windows x64, Python 3.12, Git и Inno Setup 6 для установщика.
Зависимости устанавливаются из `requirements-build.lock` с проверкой хэшей.
Сборщик проверяет fixtures, выполняет тесты, создаёт PyInstaller onedir, проверяет
содержимое пакета и лицензии, запускает EXE self-check и smoke-test без платных API.
Только после этого запускается Inno Setup. При отказе старый Setup не считается новым.

Обычная сборка:

```powershell
.\scripts\build_windows.cmd -Installer
Copy-Item dist\DND-NCFU-Setup.exe dist\setup.exe
```

Вариант через подписанный discovery владельца:

```powershell
.\scripts\build_windows.cmd -Installer -Profile tester -DiscoveryUrl 'https://raw.githubusercontent.com/sayferst/DND-NCFU/tester-host-address/endpoint.json' -DiscoveryKey '5lGcAqnkdVgVF2TlrY7TRuZyRgvdIQZZ733zsORo6eo='
Copy-Item dist\DND-NCFU-Setup.exe dist\setup_api.exe
```

DiscoveryKey — открытый ключ проверки, не секрет. В обе сборки запрещено включать
активационный bootstrap, API-ключи, DPAPI-файлы и пользовательские базы.
Общий клиент требует отдельно выданного кода после установки.

CI создаёт два раздельных артефакта с EXE и SHA256. Скачайте их из успешного запуска
Actions, проверьте результаты и прикрепите только EXE/хэши к prerelease. CI сам
не публикует релиз и не сливает PR. Релизные файлы не коммитятся в исходники.
До зелёной нативной проверки Windows готовность установщика не заявляется.
