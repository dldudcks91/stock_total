"""KakaoTalk "나에게 보내기" 메시지 클라이언트.

원본: ``upbit_project/bithumb/kakao_message_sender.py`` 를 본 프로젝트 컨벤션에
맞춰 정리.

차이점:
  - REST_API_KEY / CLIENT_SECRET / REDIRECT_URI 는 ``.env`` 에서 읽음 (코드 하드코딩 X)
  - 토큰 파일 기본 경로: ``data/alerts/kakao_token.json`` (gitignore)
  - 모듈 함수 ``get_sender()`` 와 ``setup_cli()`` 제공
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

_ROOT = Path(__file__).resolve().parents[1]
_TOKEN_PATH = _ROOT / "data" / "alerts" / "kakao_token.json"


def _load_env() -> None:
    """``.env`` 가 있으면 한 번만 로드. python-dotenv 없으면 수동 파싱."""
    env_path = _ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(env_path)
    except ImportError:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


class KakaoMessageSender:
    """카카오 '나에게 보내기' 클라이언트.

    토큰 파일에서 access/refresh 를 로드하고, 만료 10분 전에 자동 갱신한다.
    """

    AUTH_HOST = "https://kauth.kakao.com"
    API_HOST = "https://kapi.kakao.com"

    def __init__(
        self,
        rest_api_key: str,
        redirect_uri: str,
        client_secret: Optional[str] = None,
        token_path: Path = _TOKEN_PATH,
    ):
        self.rest_api_key = rest_api_key
        self.redirect_uri = redirect_uri
        self.client_secret = client_secret
        self.token_path = Path(token_path)
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self._load_token()

    # ── token persistence ──────────────────────────────────────────────
    def _save_token(self) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_expiry": self.token_expiry.isoformat() if self.token_expiry else None,
            "saved_at": datetime.now().isoformat(),
        }
        self.token_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _load_token(self) -> bool:
        if not self.token_path.exists():
            return False
        try:
            data = json.loads(self.token_path.read_text(encoding="utf-8"))
            self.access_token = data.get("access_token")
            self.refresh_token = data.get("refresh_token")
            exp = data.get("token_expiry")
            self.token_expiry = datetime.fromisoformat(exp) if exp else None
            return True
        except Exception:
            return False

    # ── OAuth ──────────────────────────────────────────────────────────
    def authorization_url(self) -> str:
        return (
            f"{self.AUTH_HOST}/oauth/authorize"
            f"?client_id={self.rest_api_key}"
            f"&redirect_uri={self.redirect_uri}"
            f"&response_type=code"
            f"&scope=talk_message"
        )

    def exchange_code(self, code: str) -> bool:
        """Authorization Code → access/refresh 토큰 교환 + 저장."""
        data = {
            "grant_type": "authorization_code",
            "client_id": self.rest_api_key,
            "redirect_uri": self.redirect_uri,
            "code": code,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        r = requests.post(f"{self.AUTH_HOST}/oauth/token", data=data, timeout=10)
        tok = r.json()
        if "access_token" not in tok:
            raise RuntimeError(f"토큰 교환 실패: {tok}")
        self.access_token = tok["access_token"]
        self.refresh_token = tok.get("refresh_token") or self.refresh_token
        self.token_expiry = datetime.now() + timedelta(seconds=int(tok.get("expires_in", 21600)))
        self._save_token()
        return True

    def refresh(self) -> bool:
        if not self.refresh_token:
            return False
        data = {
            "grant_type": "refresh_token",
            "client_id": self.rest_api_key,
            "refresh_token": self.refresh_token,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        r = requests.post(f"{self.AUTH_HOST}/oauth/token", data=data, timeout=10)
        tok = r.json()
        if "access_token" not in tok:
            return False
        self.access_token = tok["access_token"]
        if "refresh_token" in tok:
            self.refresh_token = tok["refresh_token"]
        self.token_expiry = datetime.now() + timedelta(seconds=int(tok.get("expires_in", 21600)))
        self._save_token()
        return True

    def _ensure_valid(self) -> bool:
        if not self.access_token:
            return False
        if self.token_expiry and datetime.now() >= self.token_expiry - timedelta(minutes=10):
            return self.refresh()
        return True

    # ── send ───────────────────────────────────────────────────────────
    def send_text(self, text: str, link_url: str = "https://developers.kakao.com") -> bool:
        if not self._ensure_valid():
            raise RuntimeError(
                "유효한 카카오 토큰 없음. `python -m alerts.kakao --setup` 으로 재인증."
            )
        url = f"{self.API_HOST}/v2/api/talk/memo/default/send"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        template = {
            "object_type": "text",
            "text": text,
            "link": {"web_url": link_url, "mobile_web_url": link_url},
        }
        r = requests.post(
            url, headers=headers, data={"template_object": json.dumps(template)}, timeout=10
        )
        if r.status_code != 200:
            raise RuntimeError(f"카카오 전송 실패: {r.status_code} {r.text}")
        return True


# ── factory ───────────────────────────────────────────────────────────
def get_sender(token_path: Path = _TOKEN_PATH) -> KakaoMessageSender:
    """``.env`` 의 키를 읽어 KakaoMessageSender 인스턴스 반환."""
    _load_env()
    key = os.environ.get("KAKAO_REST_API_KEY")
    if not key:
        raise RuntimeError("KAKAO_REST_API_KEY 환경변수가 없음 (.env 확인)")
    redirect = os.environ.get("KAKAO_REDIRECT_URI", "http://localhost:8080")
    secret = os.environ.get("KAKAO_CLIENT_SECRET") or None
    return KakaoMessageSender(key, redirect, secret, token_path)


# ── CLI: 최초 토큰 발급 ───────────────────────────────────────────────
def _setup_cli() -> int:
    sender = get_sender()
    if sender.access_token and sender._ensure_valid():
        print("이미 유효한 토큰이 존재합니다.")
        return 0
    print("\n인가 코드 발급을 위해 아래 URL 을 브라우저에서 여세요:")
    print(sender.authorization_url())
    print("\n로그인 후 리다이렉트된 URL 의 ?code= 뒤 문자열을 복사:")
    code = input("인가 코드: ").strip()
    sender.exchange_code(code)
    print(f"\n토큰 저장 완료: {sender.token_path}")
    return 0


def _test_cli(message: str) -> int:
    sender = get_sender()
    sender.send_text(message)
    print("전송 OK")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Kakao '나에게 보내기' 클라이언트")
    ap.add_argument("--setup", action="store_true", help="최초 토큰 발급 대화형 흐름")
    ap.add_argument("--test", metavar="MSG", help="테스트 메시지 전송")
    args = ap.parse_args()
    if args.setup:
        return _setup_cli()
    if args.test:
        return _test_cli(args.test)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
