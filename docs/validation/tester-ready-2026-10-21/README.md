#0.3.1 — проверка доставки тестировщику,21.10.2026

Среда: Linux/Python3.12.14, исходная ветка setup/development-environment.
До работы HEAD5af3602, исходный worktree чистый. Windows-инструменты владелец
подтвердил своим выводом: Python3.12.10, Git2.56.0.windows.2, cloudflared2026.10.3,
tools_ready=true. Это свидетельство инструментов, не запуска нового хоста/Setup.

## Итог

`full-final-02.txt`: **1308passed/210.41с**,0failed/skipped, pip check/Ruff check/
Ruff format успешны,208Python-файлов.20новых случаев относительно1288.
`full-01.txt`: успешный промежуточный1302/213.62с до6последних случаев.
`delivery-02.txt`: сохранён1сбой вытеснения cache при повторе старогоID из61случая;
причина исправлена, `delivery-03.txt`:36passed/11.06с, затем полный финальный.
`target-01/02` — предыдущие успешные18/69проверок, не финальнаяприёмка.

`frozen-tester-build-01.txt`: настоящий PyInstaller onedir Linux,0.3.1,
Testerprofile+Ed25519publickey+отдельныйсинтетическийbootstrap. После переноса
в `/tmp/DND проверка персонального Setup 031/bundle` и при PATH=/usr/bin:/bin,
безPYTHONPATH/PYTHONHOME/DND_TESTER_TOKEN:

- `frozen-tester-self-check-01.json`: ok=true, frozen=true, Ed25519native-roundtrip,
 8ресурсов/TLS/SQLite, сетевых0.
- `frozen-tester-smoke-01.json`: ok=true, реальныйдиалоггероя→world→чат→сцена,
 пожеланиясохранены,JSON/SQLite/RNG/визуальныйкэш/refs/вкладки,4POST+2GETloopback,
 external_model_requests=0. Настоящаяперсональнаяактивация изолирована доMainWindow.
- `frozen-tester-audit-01.json`:305файлов/272195643байта, профильподписанногоклиента,
 персональныйfixturecodeотделён отpublicprofile; нетданных/ключейвладельца.
- stderrfontconfig о недоступном системномкэше сохранён; self/smokeуспешны.

Предварительный developerbuild также создан(`frozen-developer-build-01.txt`),
но новыхпроб developerbinary не выполнялось: перенос/self/smoke здесь относятся
именно к финальнойперсональнойTesterсборке. Это ELF, неWindowsEXE/Setup.
`immutable-audit.json`:72из75файловпрежние;3обоснованныхdependencyисключения
дляcryptography, locksсхэшамисозданыuv. ПрефиксAGENTS5af3602сохранён, PowerShellBOMсохранён.

## Границы

ВнешнийQuickTunnel/GitHubbranchнепубликовались агентом; ключи/DPAPIхоста/реальные
bootstrapне генерировались длявладельца. Ключвпрофиле икод вfixture синтетические,
не обслуживаемыйдопуск. Настоящаяпубликация проверенатольковtempbareGit безсети.
Все upstream вавтотестах fake/loopback. ПлатныхмодельныхPOST0. Изменения Windows
настроек, аренда, регистрациясервисов, скачиваниеcloudflaredне выполнялись.

NativeWindows/DPAPI/Inno/cleaninstall иреальнаягенерация требуютПКвладельца:
следовать docs/TESTER_WITHOUT_DOMAIN.md. НельзяобъявлятьегоSetupготовымартефактом
до успешнойнативнойсборки и ручнойприёмки. Готов кодсборки/подключения икоманды,
а не уже развёрнутый сервер наегоWindows.
