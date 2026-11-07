"""Redacción de secretos en logs."""
import os
import re

_BLOCKS = [
    re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}"),  # bcrypt
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]
_ASSIGNMENT = re.compile(r"(?i)(password|passwd|pass|token|secret)(\s*[=:]\s*)\S+")


def redact(text: str) -> str:
    for p in _BLOCKS:
        text = p.sub("[REDACTED]", text)
    text = _ASSIGNMENT.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", text)
    for v in (os.environ.get("CHECKPOINT_PASSWORD"), os.environ.get("SAVESYNC_PASSWORD")):
        if v and len(v) >= 4:
            text = text.replace(v, "[REDACTED]")
    return text
