import re

_BYTE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class InvalidByteRange(Exception):
    def __init__(self, size: int) -> None:
        self.size = size
        super().__init__("Range not satisfiable")


def parse_byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Return an inclusive byte interval, or None when the whole object should be sent."""
    if header is None or header.strip() == "":
        return None
    if size < 0:
        raise InvalidByteRange(size)

    value = header.strip()
    if not value.lower().startswith("bytes"):
        return None
    if "," in value or size == 0:
        raise InvalidByteRange(size)

    match = _BYTE_RANGE.fullmatch(value)
    if match is None:
        raise InvalidByteRange(size)

    start_text, end_text = match.group(1), match.group(2)
    if start_text == "" and end_text == "":
        raise InvalidByteRange(size)

    if start_text == "":
        suffix = int(end_text)
        if suffix <= 0:
            raise InvalidByteRange(size)
        if suffix >= size:
            return 0, size - 1
        return size - suffix, size - 1

    start = int(start_text)
    if start >= size:
        raise InvalidByteRange(size)
    if end_text == "":
        return start, size - 1

    end = int(end_text)
    if end < start:
        raise InvalidByteRange(size)
    if end >= size:
        end = size - 1
    return start, end
