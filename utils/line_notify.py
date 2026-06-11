import os
import time
import urllib.request
import urllib.parse
import json

LINE_CHANNEL_ID = os.getenv("LINE_CHANNEL_ID", "2010370100")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_ADMIN_USER_ID = os.getenv("LINE_ADMIN_USER_ID", "")

_token_cache: dict = {"token": None, "expires_at": 0.0}


def _get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 120:
        return _token_cache["token"]

    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": LINE_CHANNEL_ID,
        "client_secret": LINE_CHANNEL_SECRET,
    }).encode()
    req = urllib.request.Request(
        "https://api.line.me/v2/oauth/accessToken",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
    _token_cache["token"] = body["access_token"]
    _token_cache["expires_at"] = now + body.get("expires_in", 2592000)
    return _token_cache["token"]


def push_text(user_id: str, text: str) -> bool:
    if not user_id or not LINE_CHANNEL_SECRET:
        return False
    try:
        token = _get_access_token()
        payload = json.dumps({
            "to": user_id,
            "messages": [{"type": "text", "text": text}],
        }).encode()
        req = urllib.request.Request(
            "https://api.line.me/v2/bot/message/push",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


def notify_admin(text: str) -> bool:
    return push_text(LINE_ADMIN_USER_ID, text)
