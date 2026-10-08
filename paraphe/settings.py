# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Paraphe contributors
"""Preferences kept between runs, in ~/.config/paraphe/settings.json."""

import json
import os

from gi.repository import GLib

DEFAULTS = {
    # Write the open file a moment after each change.
    "autosave": False,
}


def _path():
    return os.path.join(GLib.get_user_config_dir(), "paraphe", "settings.json")


def load():
    values = dict(DEFAULTS)
    try:
        with open(_path()) as f:
            stored = json.load(f)
        values.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return values


def save(values):
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(values, f, indent=2)
    os.replace(tmp, path)
