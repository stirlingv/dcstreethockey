#!/usr/bin/env python
import os
import sys
import types
import dotenv

dotenv.load_dotenv()

# django.utils.itercompat was removed in Django 4.0 but dal_select2 still imports it.
# Provide a shim so the server starts cleanly on Django 4.x.
if "django.utils.itercompat" not in sys.modules:
    _compat = types.ModuleType("django.utils.itercompat")
    _compat.is_iterable = lambda x: hasattr(x, "__iter__")
    sys.modules["django.utils.itercompat"] = _compat

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dcstreethockey.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
