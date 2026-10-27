# Карта замены

B: domain/unified.py — каталог, формулы, транзакции; unified_session.py —
создание, проверки, детерминированное продолжение; application/storage — reader30.
C: ui/creation_dialog.py — четыре шага; main_window — один новый поток;
ui/unified_panel.py — операции единого героя; старые панели только для совместимости.
D: learning/embedded.py + data/approved_knowledge — автоматический компактный
источник; developer_panel/campaign_v5_panel — убрать видимый импорт и режимы.
E: training/ — отдельные inspect/prepare/split/train/evaluate/export,
без ML-зависимостей в клиенте. Обучение только при выполненных prerequisites.
F: story_prompt/master/ollama — новые правила, адаптивная длина и проверенный
внутренний narrator backend с возвратом к RouterAI без повторной транзакции.
G: тесты новых функций и всех старых reader, скриншоты offscreen, полный check.
Не удалять старые fixtures и замороженные обработчики ради нового UI.
