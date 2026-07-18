# Kaon Bot

게임들의 공식 sns에 올라오는 새 소식을 실시간으로 구독하는 서비스

GeekNews bot처럼 discord에 자동으로 소식을 전달해 줄 수 있음

## 기능

- 게임 카탈로그(game_catalog): Kaon 개발자가 `/catalog_add`·`/catalog_remove`·`/catalog_list`로 게임별 서버(지역)의
  youtube·twitter·reddit 등 피드 URL을 미리 등록해두는 마스터 목록. `BOT_OWNER_IDS`에 등록된 유저만 사용 가능
- 사용자는 `/games`로 등록된 게임/서버 목록을 확인하고, `/subscribe`에서 게임·서버를 선택하기만 하면 구독 가능
  (URL을 직접 입력하지 않음)
- 구독한 게임의 새 소식 sns을 실시간으로 받아 옴
- 받아온 데이터를 discord 등에 올리기
  - 이때, 각 게임/서버별로 어떤 채널에 소식을 올릴 지도 사용자가 결정 가능하게 구현해야 함(디스코드 명령어를 통해)

## 디렉토리 구조

```
kaon-bot.py          # 진입점. 봇 초기화, on_ready, feature setup 호출만 담당
db.py                # SQLite 헬퍼 (get_db, run_db, init_db, last_sent_at 등 공용 DB 함수)
features/
  rss/
    __init__.py      # setup(client, tree, debug) 진입점. 커맨드 등록 + task 반환
    feed.py          # URL 변환, 피드 파싱, embed 빌드, Discord 전송 로직
    catalog.py       # game_catalog(게임/서버/피드 마스터 목록) CRUD 및 자동완성용 조회 헬퍼
    commands.py      # 슬래시 커맨드 정의 (register 함수로 tree에 등록)
    tasks.py         # 폴링 루프 (create_check_feeds 팩토리 함수)
```

## 새 기능 추가 시 유의사항

### 구조
- `features/<기능명>/` 폴더를 만든다
- `__init__.py`에 `setup(client, tree, debug)` 함수를 구현한다
- `kaon-bot.py`에서 `setup()`을 호출하고 반환된 task가 있으면 `on_ready`에서 시작한다

### DB
- 테이블 추가는 `db.py`의 `init_db()` `executescript` 안에 추가한다
- 공용으로 쓸 DB 헬퍼는 `db.py`에, feature 전용 헬퍼는 해당 feature 폴더 안에 둔다
- 모든 동기 DB 호출은 `run_db(fn)`으로 감싸 이벤트 루프 블로킹을 방지한다

### 로그
- 일반 동작 로그는 `debug` 플래그 확인 후 출력한다
- 에러는 `[ERROR]` 접두사로 항상 출력한다
- `debug` 값은 `.env`의 `DEBUG` 환경변수로 제어한다 (`DEBUG=true`)

### 기타
- 슬래시 커맨드는 `commands.py`의 `register(tree, client, debug)` 패턴을 따른다
- 백그라운드 루프는 `tasks.py`에 팩토리 함수(`create_*`) 형태로 작성한다
- `kaon-bot.py`는 최대한 얇게 유지한다. 비즈니스 로직은 feature 안에 둔다