"""Console logger for the UE Format importer.

Colored, timestamped, with optional per-operation timers. The output
prefix [XNeko/UEFORMAT] matches the framework's log style so a user
reading the console sees a single unified stream.

The NoLog switch can be driven externally; the framework's
debug_registration preference is a natural source of truth, but the
importer does not require it.
"""

import time
from typing import ClassVar


class Log:
    INFO = "\u001b[36m"
    WARN = "\u001b[33m"
    ERROR = "\u001b[31m"
    RESET = "\u001b[0m"

    PREFIX = "[XNeko/UEFORMAT]"

    NoLog: bool = False

    timers: ClassVar[dict[str, float]] = {}

    @classmethod
    def info(cls, message: str) -> None:
        if not cls.NoLog:
            print(f"{cls.INFO}{cls.PREFIX} {cls.RESET}{message}")

    @classmethod
    def warn(cls, message: str) -> None:
        if not cls.NoLog:
            print(f"{cls.WARN}{cls.PREFIX} {cls.RESET}{message}")

    @classmethod
    def error(cls, message: str) -> None:
        if not cls.NoLog:
            print(f"{cls.ERROR}{cls.PREFIX} {cls.RESET}{message}")

    @classmethod
    def time_start(cls, name: str) -> None:
        if not cls.NoLog:
            cls.timers[name] = time.time()

    @classmethod
    def time_end(cls, name: str) -> None:
        if cls.NoLog:
            return
        start_time = cls.timers.pop(name, None)
        if start_time is None:
            cls.error(f"Timer {name} does not exist")
        else:
            cls.info(f"{name} took {time.time() - start_time} seconds")