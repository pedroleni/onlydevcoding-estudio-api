import re

PATRON_PREVIA = re.compile(
    r"^previa-v(\d+)(?:-([a-z0-9][a-z0-9-]{0,60}))?\.mp4$",
    re.IGNORECASE,
)
