# Формат и воспроизводимость

gm-sft-v1:sample_id,campaign_id,scene_mode,public_context,player_message,
engine_receipt,assistant_reply,review_status,rights_status. Дополнительные
публичные knowledge_type/approved_for_public_knowledge требуют явного ревью.
Неизвестные частные поля отклоняются. engine_receipt не придумывается по прозе.

Manifest содержит SHA источника/допущенных объектов,числа и причины отказов,
privacy-review flag,состав train/val/test и group diagnostics. Кампании и найденные
почти-дубли держатся вместе. Это приближённый near-dedup,не доказательство
семантической независимости всех историй. Секреты/PII/инструкции в тексте
отклоняются консервативно; требуется ручное ревью,не автоматическая сертификация.

Никаких датасетов в Git. Фиксированный seed37, локальный immutable model revision,
assistant-only labels и EOS, реальные Trainer steps и safetensors SHA в manifest.
Каждый новый output — отдельная папка,прошлые результаты не перезаписываются.
