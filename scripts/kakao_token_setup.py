"""
카카오 OAuth 최초 1회 토큰 발급 스크립트
─────────────────────────────────────────
실행 전 준비:
  1. https://developers.kakao.com 에서 앱 생성
  2. '카카오 로그인' 활성화 + Redirect URI 등록 → http://localhost:5000/callback
  3. '나에게 보내기' 권한 활성화 (카카오싱크 없이 개인용은 기본 활성화)
  4. REST API 키를 .env 의 KAKAO_REST_API_KEY 에 입력

실행:
  python scripts/kakao_token_setup.py

완료되면 .env 에 KAKAO_REFRESH_TOKEN 이 자동 기록됩니다.
"""
import os
import sys
import json
import webbrowser

try:
    from flask import Flask, request as flask_request
except ImportError:
    sys.exit("Flask가 필요합니다: pip install flask")

try:
    import requests
except ImportError:
    sys.exit("requests가 필요합니다: pip install requests")

from pathlib import Path

# ── .env 경로 (스크립트 위치 기준 상위 폴더) ─────────────────────────
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
REDIRECT_URI = "http://localhost:5000/callback"

# .env 로드
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except ImportError:
    pass  # python-dotenv 없으면 수동으로 읽음

REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "")
if not REST_API_KEY:
    print(f"\n❌ .env ({ENV_PATH}) 에 KAKAO_REST_API_KEY 를 먼저 입력하세요.\n")
    sys.exit(1)


def _update_env(key: str, value: str) -> None:
    """·env 파일에 키=값 추가 또는 교체."""
    if not ENV_PATH.exists():
        ENV_PATH.write_text(f"{key}={value}\n", encoding="utf-8")
        return
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines, found = [], False
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    ENV_PATH.write_text("".join(new_lines), encoding="utf-8")


app = Flask(__name__)
_token_result: dict = {}


@app.route("/")
def index():
    auth_url = (
        "https://kauth.kakao.com/oauth/authorize"
        f"?client_id={REST_API_KEY}"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_type=code"
        "&scope=talk_message"
    )
    return f'<a href="{auth_url}">카카오 로그인하여 인가코드 받기</a>'


@app.route("/callback")
def callback():
    code = flask_request.args.get("code", "")
    error = flask_request.args.get("error", "")
    if error or not code:
        return f"<h3>오류: {error}</h3><p>창을 닫고 다시 시도하세요.</p>", 400

    # 인가코드 → 토큰 교환
    resp = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": REST_API_KEY,
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        timeout=10,
    )
    data = resp.json()
    if "access_token" not in data:
        return f"<h3>토큰 교환 실패</h3><pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre>", 400

    access_token = data["access_token"]
    refresh_token = data["refresh_token"]

    # .env 저장
    _update_env("KAKAO_REFRESH_TOKEN", refresh_token)

    _token_result["done"] = True
    print(f"\n✅ 토큰 발급 완료")
    print(f"   access_token  : {access_token[:20]}…")
    print(f"   refresh_token : {refresh_token[:20]}…")
    print(f"   → .env 에 KAKAO_REFRESH_TOKEN 저장 완료: {ENV_PATH}\n")

    return (
        "<h3>✅ 카카오 토큰 발급 완료</h3>"
        "<p>이 창을 닫고 터미널로 돌아가세요.<br>"
        "이제 InvestOS 브리핑 모듈에서 카카오톡 발송을 사용할 수 있습니다.</p>"
    )


if __name__ == "__main__":
    url = "http://localhost:5000"
    print("\n========================================")
    print(" 카카오 OAuth 토큰 발급 도우미")
    print("========================================")
    print(f" 1. 브라우저가 열리면 카카오 계정으로 로그인")
    print(f" 2. 동의 후 자동으로 토큰이 .env 에 저장됩니다")
    print(f" 3. 완료 후 이 터미널에서 Ctrl+C 로 종료\n")
    webbrowser.open(url)
    app.run(host="127.0.0.1", port=5000, debug=False)
