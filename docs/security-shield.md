# Security shield

`security_shield.py` sits in front of every request to the website. It rate
limits each client IP, blocks clients that are clearly attacking, and raises an
alert the moment something large happens. The limits are generous on purpose:
normal browsing never meets them.

## What it does

| Signal (per IP) | Default | What happens |
| --- | --- | --- |
| Requests per minute | 600 | Over: `429 Too Many Requests`. Twice that (ignored the 429s): **blocked** |
| Writes (POST/PUT/PATCH/DELETE) per minute | 120 | Same as above |
| Static files per minute | 2400 | Same as above |
| Requests for exploit paths (`/.env`, `/wp-login.php`, `/.git/…`, `*.php`, …) | 3 in 10 min | Answered 404; the third **blocks** |
| 404 responses | 200 in 10 min | **Blocked** (scanner) |
| Failed logins (401/403 to requests that carried credentials) | 30 in 10 min | **Blocked** (password guessing) |

Blocks last 15 minutes, then 1 hour, then 24 hours for repeat offenders, and
are saved to storage (`owner/security-blocks.json`) so a redeploy doesn't let
anyone back in.

Site-wide it also alerts on a traffic surge (6000 requests/minute across all
visitors) and on many different IPs hitting limits at once (20 in 10 minutes),
which is what a distributed attack looks like even when no single IP crosses a
line.

Never limited: signed-in portal admins (so you can't lock yourself out from a
shared network), `/health`, addresses in `SECURITY_ALLOWLIST`, and internal
addresses (if every visitor resolved to one internal address, limiting it would
take the site down; a warning is logged instead).

The same middleware also:

* caps request bodies at 8 MB (30 MB for file uploads) so a huge upload can't
  exhaust memory or disk;
* refuses state-changing requests a browser reports as cross-site
  (`Sec-Fetch-Site: cross-site`), a CSRF defence that holds even if
  `SESSION_COOKIE_SAMESITE` is set to `none`. `DASHBOARD_ORIGIN` is allowed.

## Client IPs

Rate limits are only as good as the IP they key on. The first
`X-Forwarded-For` entry is whatever the client chose to send, so the shield
reads the chain from the right (what our own proxies appended), skips our own
hops (private/Railway addresses and Cloudflare's published ranges) and takes
`CF-Connecting-IP` only when the request really came through Cloudflare. A
client therefore can't dodge its budget, or get someone else blocked, with a
forged header. The rest of the app (activity feed, admin presence, chat limits)
uses the same resolver.

If your hosting differs, set `SECURITY_CLIENT_IP_HEADER` (for example
`cf-connecting-ip`) or add proxy ranges to `SECURITY_TRUSTED_PROXIES`.

## Getting alerted

Every block, surge and AI-budget exhaustion is:

1. logged (`Security shield: …`, at ERROR for critical incidents);
2. added to the director's activity feed as a **Security Alert** (live on the
   Security Overview page);
3. posted to Discord if one of these is set:
   * `SECURITY_ALERT_WEBHOOK_URL`: a Discord channel webhook URL, or
   * `SECURITY_ALERT_CHANNEL_ID`: a channel the bot can post in.

   `SECURITY_ALERT_MENTION` (for example `<@&123456789>`) is prepended to
   critical alerts to ping a role. Alerts are capped at 10 per 5 minutes; the
   rest are summarised so an attack can't flood the channel.

## Director controls

**Director → Security Overview → Automated Defences** shows the shield status,
requests per minute, every blocked IP (with reason, time left and hits since
the block) and recent incidents. Directors can unblock an IP or block one by
hand for 1 hour to 30 days.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `SECURITY_SHIELD` | `on` | `off` disables rate limiting and blocking entirely |
| `SECURITY_AUTO_BLOCK` | `on` | `off`: throttle and alert, but never block automatically |
| `SECURITY_REQUESTS_PER_MINUTE` | 600 | Per-IP request budget |
| `SECURITY_WRITES_PER_MINUTE` | 120 | Per-IP write budget |
| `SECURITY_ASSETS_PER_MINUTE` | 2400 | Per-IP static-file budget |
| `SECURITY_FAILED_LOGIN_LIMIT` | 30 | Failed logins per 10 minutes before a block |
| `SECURITY_NOT_FOUND_LIMIT` | 200 | 404s per 10 minutes before a block |
| `SECURITY_PROBE_LIMIT` | 3 | Exploit-path requests per 10 minutes before a block |
| `SECURITY_SURGE_ALERT_PER_MINUTE` | 6000 | Site-wide requests per minute that raise an alert |
| `SECURITY_SURGE_ALERT_IPS` | 20 | Distinct throttled IPs (10 min) that raise an alert |
| `SECURITY_MAX_BODY_MB` / `SECURITY_MAX_UPLOAD_MB` | 8 / 51 | Request body caps (uploads leave room for 50 MB Project ZETA files) |
| `SECURITY_ALLOWLIST` | | Comma-separated IPs/CIDRs never limited |
| `SECURITY_CLIENT_IP_HEADER` | | Trust this one header for the client IP |
| `SECURITY_TRUSTED_PROXIES` | | Extra proxy CIDRs to skip in `X-Forwarded-For` |
| `ALICE_DAILY_COMMANDS_PER_USER` / `ALICE_DAILY_COMMANDS_TOTAL` | 150 / 1500 | Daily caps on paid A.L.I.C.E. model calls |

## What it can't do

The shield runs inside the app, so it stops abusive clients cheaply but can't
absorb a volumetric DDoS: that has to be dropped before it reaches Railway.
Turn on Cloudflare's DDoS protection and add a Cloudflare rate-limiting rule as
an outer layer; the shield keeps working behind it.

## Audit notes (October 2026)

Fixed alongside the shield:

* **Spoofable client IPs** everywhere (activity feed, admin presence IPs, chat
  rate limits): now resolved as described above.
* **Operator passwords** were unsalted SHA-256. They are now bcrypt, and old
  hashes are upgraded on the operator's next successful login.
* **Admin API tokens** (8 hours) kept working after someone was removed from
  the admin team. Admin and director tokens are now re-checked against the
  current team on every use, including the moderation API.
* **A.L.I.C.E. terminal**: any Discord account could make paid model calls;
  added per-account and site-wide daily caps, with an alert when the site-wide
  cap is hit.
* **Headers**: added `Strict-Transport-Security` and
  `Cross-Origin-Opener-Policy`.
* **No brute-force protection** on HTTP Basic auth and API tokens, no request
  size cap, no CSRF check beyond SameSite: covered by the shield.
* Warns at start-up when `SESSION_SECRET` is missing or short.

Still worth doing:

* Set long random `SESSION_SECRET` and `JWT_SECRET` values in Railway if they
  aren't already. Without them sessions and tokens reset on every restart, and
  a short session secret can be brute-forced to forge an admin session.
* Page scripts are inline, so the Content-Security-Policy has to allow
  `'unsafe-inline'` scripts and gives no protection against injected script.
  Moving inline scripts to files (or adding nonces) would close that.
* The Discord OAuth access token is kept in the signed (but not encrypted)
  session cookie. Only its owner can read it, but it would be safer server-side.
