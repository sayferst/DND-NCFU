# Права и сторонние материалы

## Код проекта

Владелец пока не выбрал лицензию исходного кода DND-NCFU. Публичная доступность
репозитория не является разрешением на произвольное использование и распространение.
Отдельная лицензия MIT/GPL/Apache для авторского кода здесь не назначена.
Перед распространением сборок уточните разрешение владельца и обязательства зависимостей.

## SRD

This work includes material from the System Reference Document 5.2.1 (“SRD 5.2.1”)
by Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd.
The SRD 5.2.1 is licensed under the Creative Commons Attribution 4.0 International
License, available at https://creativecommons.org/licenses/by/4.0/legalcode.

Русские названия и вычислительная реализация подмножества правил являются адаптацией.
Характеристики, модификатор `(score - 10) // 2` и проверки d20 используют материал SRD.
Профили героя, экономика, сюжет, конфликты и развитие содержат авторские homebrew-механики;
игра не реализует полные правила D&D. Проект не одобрен Wizards of the Coast.
Лицензия SRD не распространяется автоматически на код, изображения или товарные знаки.

## Оформление

`kingdom.png` и `world-creation-atlas.png` созданы инструментом генерации изображений
OpenAI по поручению владельца для этого проекта. Это декорации интерфейса, не фотографии
или изображения личных кампаний и не материалы SRD. Отдельная свободная лицензия на них
не назначена. Иконка щита/меча построена средствами QPainter; чужие логотипы не использованы.
Шрифты не поставляются: приложение использует системные шрифты и замены Qt.

## Зависимости

| Компонент | Условия |
| --- | --- |
| Python | PSF; https://docs.python.org/3/license.html |
| SQLite | Public domain; https://sqlite.org/copyright.html |
| PySide6 Essentials / shiboken6 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| cffi / pycparser | MIT-0 / BSD-3-Clause |
| PyInstaller | GPL-2.0-or-later с исключением для собранных приложений |
| pytest / Ruff | MIT |

Точные версии и хэши — в lock-файлах. Полные уведомления Qt/OpenSSL хранятся
в `licenses/third-party`; сборщик также копирует LICENSE из установленных пакетов.
Qt загружается динамически; упаковка не отменяет требований LGPL и доступности
соответствующих исходников. Источники: https://doc.qt.io/qtforpython-6/licenses.html,
https://code.qt.io/cgit/pyside/pyside-setup.git/ и https://pyinstaller.org/en/stable/license.html.
Это описание происхождения и условий, а не юридическая сертификация сборки.

Модели и их веса не поставляются. Условия Ollama, выбранных моделей и API-провайдеров
проверяются отдельно; оплата облачного API не означает получение свободной лицензии
на модель или сгенерированные изображения.
