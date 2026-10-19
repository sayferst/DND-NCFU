# Повторный отчёт Windows: эталон и тест Git

Источник: текст, вставленный пользователем в чат 19 октября 2026.
Это выдержки, записанные агентом в UTF-8, не исходный файл консоли; исходная
кодировка, переводы строк и байтовая контрольная сумма консоли неизвестны.
Среда по путям: Windows, PowerShell, проект `D:\Projects\DND-NCFU`.
Команды обновления и текущий коммит в этом сообщении не показаны.

```text
FAILED tests/test_fixture_git_checkout.py::test_windows_git_checkout_preserves_fixture_bytes_and_original_sha256
    assert converted == original.replace(b"\n", b"\r\n")
E   At index 2 diff: b'\n' != b'\r'

FAILED tests/test_mechanics_before_prose.py::test_real_v15_fixture_is_not_reparsed_or_rewritten
    assert hashlib.sha256(raw).hexdigest() == source["sha256"]
E   - e00a333d44929de6d5e3ff6a87c70ca3e1b1f9704f55554ecaf2cb59bed94238
E   + b1d9736c8d31f59f331da4e74ee2850f7f211488b2bbd6ff59f9f1e5b1d420f2

2 failed, 676 passed in 34.61s
Проверка не прошла. Сохраните вывод.
PS D:\Projects\DND-NCFU>
```

Вывод агента: рабочий эталон имеет ранее воспроизведённую CRLF-сумму. В Git-тесте
повторное LF→CRLF над этой копией порождает CRCRLF. Это две ошибки проверок;
данных об отказе настоящего RouterAI, повреждении сохранений или новом игровом
формате в сообщении нет. Причина сохранения старой копии после прежних инструкций
по этому выводу не установлена.
