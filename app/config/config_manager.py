"""User configuration: one small JSON file under %APPDATA%\\ZeroPort.

Deliberately not a settings framework. Read on start, write on change, and
never let a malformed file stop the app from opening — a corrupt config falls
back to defaults rather than raising.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

APP_DIR_NAME = "ZeroPort"
CONFIG_FILE_NAME = "config.json"

ALLOWED_INTERVALS = (2, 5, 10, 30)

DEFAULT_CONFIG: Dict[str, Any] = {
    "auto_refresh": True,
    "refresh_interval": 5,
    "window": {"width": 1100, "height": 700, "maximized": False},
    "custom_descriptions": {},
}


def config_dir() -> Path:
    """Per-user config location. Never the install directory."""
    base = os.environ.get("APPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / APP_DIR_NAME


def config_path() -> Path:
    return config_dir() / CONFIG_FILE_NAME


class ConfigManager:
    """Loads, validates and persists the user's settings."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else config_path()
        self._data: Dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))
        self.load_error: Optional[str] = None
        self.quarantine_path: Optional[Path] = None
        self.load()

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------ load

    def load(self) -> None:
        self.load_error = None
        try:
            # utf-8-sig, not utf-8: Notepad and PowerShell both write a BOM,
            # and a config the user edited by hand must still load.
            raw = self._path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return
        except OSError as exc:
            self.load_error = f"Could not read config: {exc}"
            return

        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError) as exc:
            self._quarantine(f"is not valid JSON: {exc}")
            return

        if not isinstance(parsed, dict):
            self._quarantine("must contain a JSON object")
            return

        self._data = self._sanitise(parsed)

    def _quarantine(self, problem: str) -> None:
        """Move an unreadable config aside instead of overwriting it.

        The app saves on exit, so without this a single typo in a hand-edited
        file would silently destroy every custom port name in it.
        """
        self.load_error = f"Config file {problem}."
        try:
            backup = self._path.with_name(self._path.stem + ".invalid.json")
            os.replace(self._path, backup)
        except OSError:
            self.quarantine_path = None
            return
        self.quarantine_path = backup
        self.load_error = (
            f"Your config file {problem}. "
            f"It was kept as {backup.name} and ZeroPort started with defaults."
        )

    def _sanitise(self, parsed: Mapping[str, Any]) -> Dict[str, Any]:
        data = json.loads(json.dumps(DEFAULT_CONFIG))

        if isinstance(parsed.get("auto_refresh"), bool):
            data["auto_refresh"] = parsed["auto_refresh"]

        interval = parsed.get("refresh_interval")
        if isinstance(interval, (int, float)) and int(interval) in ALLOWED_INTERVALS:
            data["refresh_interval"] = int(interval)

        window = parsed.get("window")
        if isinstance(window, Mapping):
            width = window.get("width")
            height = window.get("height")
            if isinstance(width, (int, float)) and 850 <= int(width) <= 10000:
                data["window"]["width"] = int(width)
            if isinstance(height, (int, float)) and 500 <= int(height) <= 10000:
                data["window"]["height"] = int(height)
            if isinstance(window.get("maximized"), bool):
                data["window"]["maximized"] = window["maximized"]

        data["custom_descriptions"] = self._sanitise_descriptions(
            parsed.get("custom_descriptions")
        )
        return data

    @staticmethod
    def _sanitise_descriptions(raw: Any) -> Dict[str, str]:
        """Keep only ``"<valid port>": "<non-empty label>"`` pairs."""
        if not isinstance(raw, Mapping):
            return {}
        cleaned: Dict[str, str] = {}
        for key, value in raw.items():
            try:
                port = int(str(key).strip())
            except (TypeError, ValueError):
                continue
            if not 0 < port <= 65535:
                continue
            if not isinstance(value, str):
                continue
            label = value.strip()
            if label:
                cleaned[str(port)] = label[:120]
        return cleaned

    # ------------------------------------------------------------------ save

    def save(self) -> Optional[str]:
        """Persist atomically. Returns an error string, or None on success."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self._data, indent=2, ensure_ascii=False)
            # Write to a sibling temp file then replace, so a crash mid-write
            # cannot leave a truncated config behind.
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self._path.parent), prefix=".config-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                os.replace(tmp_name, self._path)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except OSError as exc:
            return f"Could not save config: {exc}"
        return None

    # -------------------------------------------------------------- accessors

    @property
    def auto_refresh(self) -> bool:
        return bool(self._data["auto_refresh"])

    @property
    def refresh_interval(self) -> int:
        return int(self._data["refresh_interval"])

    def set_refresh(self, enabled: bool, interval: Optional[int] = None) -> None:
        self._data["auto_refresh"] = bool(enabled)
        if interval is not None and int(interval) in ALLOWED_INTERVALS:
            self._data["refresh_interval"] = int(interval)
        self.save()

    @property
    def custom_descriptions(self) -> Dict[str, str]:
        return dict(self._data["custom_descriptions"])

    def set_custom_descriptions(self, mapping: Mapping[str, str]) -> None:
        self._data["custom_descriptions"] = self._sanitise_descriptions(mapping)
        self.save()

    @property
    def window_size(self) -> tuple[int, int]:
        window = self._data["window"]
        return int(window["width"]), int(window["height"])

    @property
    def window_maximized(self) -> bool:
        return bool(self._data["window"]["maximized"])

    def set_window_state(self, width: int, height: int, maximized: bool) -> None:
        window = self._data["window"]
        if not maximized and width >= 850 and height >= 500:
            window["width"] = int(width)
            window["height"] = int(height)
        window["maximized"] = bool(maximized)
        self.save()

    def as_dict(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self._data))

    def ensure_file_exists(self) -> Optional[str]:
        """Create the config file if it is missing, so users can find and edit it."""
        if self._path.exists():
            return None
        return self.save()
