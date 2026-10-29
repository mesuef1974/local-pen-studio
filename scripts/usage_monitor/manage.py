#!/usr/bin/env python
"""Django management entry point for the local usage dashboard."""

from __future__ import annotations

import os
import sys


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard_project.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
