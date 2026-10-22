# Windows build: слишком длинное имя теста

Реальный вывод владельца:1491passed/2errors за297.83с. Обеошибкиsetup/teardown
одного test_invalid_dns_reply_is_not_used: pytest включил bytes65537 целиком
вnodeid, Windowsотклонила PYTEST_CURRENT_TEST длиннее32767символов.
Отдельный atexitcleanupPermissionError не основнаяпричинаостановки.

Короткиеявныеids сохраняют payload/размер/asserts. Существующаярегрессия теперь
собирает весьнабор, проверяет UTF16длинуids сteardownсуффиксом, прежниеpromptids
и DNSoversized. Игровойкод, проверкисети и сборщик не менялись.

Реально выполнено вLinux: `.venv/bin/python -m pytest -q tests/test_tunnel_dns.py
tests/test_windows_test_ids.py` —20passed/1.42с; включает collect-only всегонабора.
Ruffcheck/formatдвухизменённыхPythonфайлов пройден. Полныйнабор не повторялся:
измененытолькоtestids/collectionрегрессия. ПредыдущийLinux1492passed сохранён
вngrok-agent-version-2026-10-22. НовогоWindowsпрогона здесь нет.

Владелец подтвердил ngrok3.39.12 и3HTTPSуспеха. Оставитьstart и выполнитьpull/build
tester1 во второмокне. Не отключатьchecks, не менятьTempACL/Windows/VPN.
