# byte-files-publish

Publisher **code only** for The Byte Files (YouTube, Facebook, TikTok and Buffer Shorts).

This repo is public so GitHub Actions is free. It holds **no data**: the schedule, kits, videos, tokens and logs live in a private repository. Each workflow checks that data out with a repository secret, runs the code in `publish/` and `tools/` against it, saves the results back to the private repository, and prints only an `ok`/`failed` line here.

| Workflow | When | What it does |
|---|---|---|
| `publish.yml` | twice a day + manual | Sends Shorts (and long-episode TikTok rows) to Buffer |
| `publish-long.yml`, `facebook-live.yml` | daily / twice a day | Schedules long episodes on Facebook; first comment once live |
| `publish-youtube.yml`, `youtube-live.yml` | daily / twice a day | Schedules long episodes on YouTube; first comment once public |
| `publish-tiktok.yml` | 3 times a day | Posts long episodes on TikTok (off until `TT_AUTO=1`) |
| `r2.yml` | every 10 min + manual | Copies media from `upload/*` branches of the private repo to Cloudflare R2 |
| `tiktok-cuts.yml`, `short-covers.yml`, `short-frames.yml`, `youtube-comment.yml`, `tiktok-auth.yml`, `r2-organize.yml` | manual | Helpers |
| `keepalive.yml` | monthly | One empty commit so GitHub does not switch the schedules off |

Secrets: `HUB_TOKEN` (fine-grained, private data repo only, Contents read/write), `FB_*`, `YT_*`, `TT_*`, `BUFFER_ACCESS_TOKEN`, `R2_*`. Variables (`FB_AUTO`, `YT_AUTO`, `TT_AUTO`, `TT_PRIVACY`, `TT_MODE`) stay as they are.
