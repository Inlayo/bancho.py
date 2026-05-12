from __future__ import annotations

import re

username = re.compile(r"^[\w \[\]-]{2,15}$")
email = re.compile(r"^[^@\s]{1,200}@[^@\s\.]{1,30}\.[^@\.\s]{1,24}$")
