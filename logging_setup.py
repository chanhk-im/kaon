import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from logging.handlers import TimedRotatingFileHandler

KST = ZoneInfo("Asia/Seoul")


class KSTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=KST)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def format(self, record):
        time_str = self.formatTime(record)
        level = record.levelname.ljust(8)
        return f"[{time_str}] [{level}] {record.name}: {record.getMessage()}"


class ShardIdNoneFilter(logging.Filter):
    """discord.py가 샤딩 미사용 시 출력하는 'Shard ID None' 메시지를 정제한다."""
    def filter(self, record):
        if record.name == "discord.gateway" and "Shard ID None" in record.getMessage():
            record.msg = record.msg.replace("Shard ID %s", "").replace("Shard ID None", "").strip()
            if record.args and len(record.args) > 0:
                # shard_id가 첫 번째 arg인 경우 제거
                args = list(record.args)
                if args and args[0] is None:
                    args.pop(0)
                record.args = tuple(args)
        return True


def setup_logging(debug: bool = False):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, "log")
    os.makedirs(log_dir, exist_ok=True)

    level = logging.DEBUG if debug else logging.INFO
    formatter = KSTFormatter()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    log_filename = os.path.join(log_dir, datetime.now(tz=KST).strftime("%Y-%m-%d") + ".log")
    file_handler = TimedRotatingFileHandler(
        log_filename, when="midnight", interval=1, backupCount=30,
        encoding="utf-8", atTime=None,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    file_handler.suffix = "%Y-%m-%d.log"

    shard_filter = ShardIdNoneFilter()

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    logging.getLogger("discord").addFilter(shard_filter)
