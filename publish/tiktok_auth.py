"""The Byte Files — one-time TikTok sign-in: swap the authorize code for tokens and keep the refresh token encrypted.

1. Open the authorize link (see README "TikTok sign-in"), sign in as the TikTok account and press Authorize.
2. TikTok sends the browser to https://github.com/devsuresh120-coder/byte-files?code=...&state=...
   Copy the whole address (or just the code) into the workflow "TikTok sign-in" and run it within a few minutes.
Env: TT_CLIENT_KEY, TT_CLIENT_SECRET (secrets), CODE (workflow input).
"""
import os, sys
from urllib.parse import urlparse, parse_qs, unquote
import publish_tiktok as T

REDIRECT = "https://github.com/devsuresh120-coder/byte-files"


def main():
    raw = os.environ.get("CODE", "").strip()
    if not raw:
        sys.exit("paste the code (or the whole address after Authorize) into the 'code' input")
    code = parse_qs(urlparse(raw).query).get("code", [None])[0] if "code=" in raw else unquote(raw)
    if not code:
        sys.exit("no code= found in what was pasted")
    try:
        j = T.token_request({"code": code, "grant_type": "authorization_code", "redirect_uri": REDIRECT})
    except RuntimeError as e:
        sys.exit(f"TikTok refused the code: {e}  (a code works once and only for a few minutes: authorize again and run this right away)")
    scopes = j.get("scope", "")
    print("signed in. scopes:", scopes, "| refresh token valid for", int(j.get("refresh_expires_in", 0)) // 86400, "days")
    if "video.publish" not in scopes:
        print("::warning title=video.publish missing::the account did not grant video.publish; authorize again and allow posting")
    T.save_refresh(j["refresh_token"])
    tok = j["access_token"]
    info = T.creator_info(tok)
    print(f"TikTok account: @{info.get('creator_username')} ({info.get('creator_nickname')})")
    print("privacy options:", info.get("privacy_level_options"), "| max video length (s):", info.get("max_video_post_duration_sec"))


if __name__ == "__main__":
    main()
