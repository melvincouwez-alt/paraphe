# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 melvincouwez-alt
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Granite", "7.0")
gi.require_foreign("cairo")

from .application import Application  # noqa: E402


def main():
    return Application().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
