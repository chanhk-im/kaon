"""
Redis Stream에 가짜 항목을 직접 주입해서 consumer(Discord 전송)를 테스트합니다.
봇이 실행 중인 상태에서 사용하세요.

사용법:
    python test_inject.py <discord_channel_id> [--count 3]
"""
import asyncio
import argparse
import time
import redis.asyncio as aioredis
from dotenv import load_dotenv
import os

load_dotenv()
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
STREAM_KEY = "feed:events"

FAKE_ENTRIES = [
    {
        "source_type": "YouTube",
        "game_name": "테스트 게임",
        "title": "[테스트] 새 영상 업로드됐어요!",
        "link": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "summary": "",
        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    },
    {
        "source_type": "Reddit",
        "game_name": "테스트 게임",
        "title": "[테스트] 공식 업데이트 공지",
        "link": "https://www.reddit.com/r/test/comments/test",
        "summary": "테스트용 Reddit 공지입니다. 실제 내용이 아닙니다.",
        "thumbnail_url": "",
    },
    {
        "source_type": "RSS",
        "game_name": "테스트 게임",
        "title": "[테스트] RSS 피드 항목",
        "link": "https://example.com/news/test",
        "summary": "테스트용 RSS 항목입니다. 실제 내용이 아닙니다.",
        "thumbnail_url": "",
    },
]


async def inject(channel_id: str, count: int):
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await r.ping()
    except Exception as e:
        print(f"❌ Redis 연결 실패: {e}")
        return

    entries = FAKE_ENTRIES[:count]
    for i, entry in enumerate(entries):
        entry_id = f"test-{int(time.time())}-{i}"
        fields = {**entry, "channel_id": channel_id, "entry_id": entry_id}
        msg_id = await r.xadd(STREAM_KEY, fields)
        print(f"✅ 주입 완료: [{entry['source_type']}] {entry['title']} (id={msg_id})")

    await r.aclose()
    print(f"\n총 {len(entries)}개 항목을 Stream에 주입했습니다.")
    print("봇이 실행 중이면 곧 Discord에 전송됩니다.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("channel_id", help="Discord 채널 ID")
    parser.add_argument("--count", type=int, default=3, choices=[1, 2, 3], help="주입할 항목 수 (기본값: 3)")
    args = parser.parse_args()

    asyncio.run(inject(args.channel_id, args.count))
