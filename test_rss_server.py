"""
가짜 RSS 피드를 localhost에서 서빙합니다.
폴링 → Stream 적재 → Discord 전송 전체 파이프라인을 테스트할 때 사용합니다.

사용법:
    python test_rss_server.py        # 기본 포트 8765
    python test_rss_server.py 9000   # 포트 지정

봇에서 구독:
    /subscribe game_name:테스트게임 url:http://localhost:8765/feed.rss
    (Docker 사용 시 localhost 대신 host.docker.internal 사용)
"""
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

def make_rss(num_items: int = 5) -> str:
    now = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
    items = ""
    for i in range(num_items, 0, -1):
        ts = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(time.time() - i * 60))
        items += f"""
        <item>
            <title>테스트 공지 #{i}</title>
            <link>https://example.com/news/{i}</link>
            <guid>test-entry-{i}</guid>
            <pubDate>{ts}</pubDate>
            <description>테스트용 뉴스 항목 #{i}입니다. 실제 내용이 아닙니다.</description>
        </item>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>테스트 게임 공식 뉴스</title>
    <link>https://example.com</link>
    <description>Kaon Bot 테스트용 RSS 피드</description>
    <lastBuildDate>{now}</lastBuildDate>
    {items}
  </channel>
</rss>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/feed.rss":
            self.send_response(404)
            self.end_headers()
            return

        body = make_rss().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        print(f"[RSS] 피드 요청 처리 완료")

    def log_message(self, format, *args):
        pass  # 기본 로그 억제


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"✅ 테스트 RSS 서버 시작: http://localhost:{PORT}/feed.rss")
    print(f"봇에서 구독 명령어:")
    print(f"  /subscribe game_name:테스트게임 url:http://localhost:{PORT}/feed.rss")
    print(f"  (Docker 사용 시: http://host.docker.internal:{PORT}/feed.rss)")
    print(f"\nCtrl+C로 종료")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버 종료")
