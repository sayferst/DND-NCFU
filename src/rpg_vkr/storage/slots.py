"""Three versioned JSON slots, atomically replaced on the same filesystem."""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rpg_vkr.application import Session

MAX_SAVE_BYTES = 32 * 1024 * 1024


class SaveError(Exception):
    """A recoverable save/load/delete failure suitable for a UI message."""


@dataclass(frozen=True)
class SlotInfo:
    occupied: bool
    description: str


def default_save_directory() -> Path:
    from rpg_vkr.resources import data_directory

    return data_directory() / "saves"


class SaveSlots:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, slot: int) -> Path:
        if type(slot) is not int or slot not in (1, 2, 3):
            raise ValueError("Slot must be 1, 2 or 3")
        return self.directory / f"slot-{slot}.json"

    def _read(self, slot: int) -> tuple[Session, datetime]:
        path = self._path(slot)
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_SAVE_BYTES + 1)
            if len(raw) > MAX_SAVE_BYTES:
                raise ValueError("Save too large")
            data = json.loads(raw)
            if not isinstance(data, dict) or set(data) != {"schema_version", "saved_at", "session"}:
                raise ValueError("Invalid save structure")
            if type(data["schema_version"]) is not int or data["schema_version"] not in (
                1,
                2,
                3,
                4,
                5,
                6,
                7,
                8,
                9,
                10,
                11,
                12,
                13,
                14,
                15,
                16,
                17,
                18,
                19,
                20,
                21,
                22,
                23,
                24,
                25,
                26,
                27,
                28,
                29,
                30,
                31,
            ):
                raise ValueError("Unsupported save version")
            saved_at = datetime.fromisoformat(data["saved_at"])
            if saved_at.tzinfo is None:
                raise ValueError("Missing timestamp timezone")
            saved_at = saved_at.astimezone()
            return Session.from_dict(data["session"], version=data["schema_version"]), saved_at
        except FileNotFoundError as error:
            raise SaveError("Эта ячейка пуста.") from error
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
            raise SaveError("Сохранение повреждено или имеет неподдерживаемую версию.") from error
        except OSError as error:
            raise SaveError("Не удалось прочитать сохранение. Проверьте доступ к папке.") from error

    def info(self, slot: int) -> SlotInfo:
        try:
            session, saved_at = self._read(slot)
        except SaveError as error:
            if isinstance(error.__cause__, FileNotFoundError):
                return SlotInfo(False, "пусто")
            return SlotInfo(True, "повреждено или недоступно")
        timestamp = saved_at.astimezone().strftime("%d.%m.%Y %H:%M")
        return SlotInfo(True, f"{timestamp} · действий: {len(session.turns)}")

    def load(self, slot: int) -> Session:
        return self._read(slot)[0]

    def save(self, slot: int, session: Session) -> None:
        path = self._path(slot)
        temporary = None
        try:
            payload = json.dumps(
                {
                    "schema_version": session.schema_version,
                    "saved_at": datetime.now(UTC).isoformat(),
                    "session": session.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            if len(payload) > MAX_SAVE_BYTES:
                raise SaveError("Сессия превышает допустимый размер сохранения (4 МБ).")
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self.directory, prefix=f".slot-{slot}-", suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError as error:
            raise SaveError(
                "Не удалось сохранить сессию. Проверьте свободное место и доступ."
            ) from error
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    # Cleanup must not mask the original failure or undo a successful replace.
                    pass

    def delete(self, slot: int) -> None:
        try:
            self._path(slot).unlink()
        except FileNotFoundError as error:
            raise SaveError("Эта ячейка уже пуста.") from error
        except OSError as error:
            raise SaveError("Не удалось удалить сохранение. Проверьте доступ к папке.") from error
