# Security shield

`security_shield.py` sits in front of every request to the website. It rate
limits every client, blocks clients that are clearly attacking, keeps injected
scripts from running, and raises an alert the moment something large happens.
The limits are generous on purpose: normal browsing never meets them.

**Nobody is exempt**, the owner included. Signed-in admins get much more room
(see [Admins](#admins)), but a script or a stolen session running on an admin
account is throttled and blocked like anyone else.

## What it does

| Signal | Default | What happens |
| --- | --- | --- |
| Requests per minute | 600 per IP | Over: `429 Too Many Requests`. Twice that (ignored the 429s): **blocked** |
| Writes (POST/PUT/PATCH/DELETE) per minute | 120 per IP | Same as above |
| Static files per minute | 2400 per IP | Same as above |
| Requests in progress at once | 50 per IP | Over: `429` until earlier ones finish |
| Requests from one network (IPv4 /24, IPv6 /48) | 8 × the per-IP budget | Over: `429` for that network. Twice that: the **network is blocked** |
| Exploit paths (`/.env`, `/wp-login.php`, `/.git/…`, `*.php`, …) | 3 in 10 min | Answered 404; the third **blocks** |
| Injection payloads in the URL (`<script>`, `onerror=`, `' OR '1'='1`, `UNION SELECT`, `${jndi:`, `{{7*7}}`, `;curl`, `../`, `php://`, …) | 3 in 10 min (shared with the above) | Answered 404; the third **blocks** |
| 404 responses | 200 in 10 min | **Blocked** (scanner) |
| Failed logins (401/403 to requests that carried credentials) | 30 in 10 min | **Blocked** (password or token guessing) |

An IPv6 visitor is counted as its whole /64: one connection gets billions of
IPv6 addresses, so counting them one by one would let anyone reset their budget
at will.

Blocks last 15 minutes, then 1 hour, then 24 hours for repeat offenders, and
are saved to storage (`owner/security-blocks.json`) so a redeploy doesn't let
anyone back in.

Never limited: `/health`, addresses in `SECURITY_ALLOWLIST`, and internal
addresses (if every visitor resolved to one internal address, limiting it would
take the site down; a warning is logged instead). Signed-in admins are counted
per account even from those addresses.

The same middleware also:

* caps request bodies at 8 MB (51 MB for file uploads) so a huge upload can't
  exhaust memory or disk;
* refuses state-changing requests a browser reports as cross-site
  (`Sec-Fetch-Site: cross-site`), a CSRF defence that holds even if
  `SESSION_COOKIE_SAMESITE` is set to `none`. `DASHBOARD_ORIGIN` is allowed;
* ties every signed-in session to the browser it was first used from (see
  [Stolen sessions](#stolen-sessions)).

## Admins

Admins (portal managers and the owner, whether signed in with Discord, a staff
API token or the dashboard's HTTP Basic login) are **counted per account**,
not per IP, against limits `SECURITY_ADMIN_LIMIT_FACTOR` times larger (5 by
default):

| | Anonymous (per IP) | Admin (per account) |
| --- | --- | --- |
| Requests per minute | 600 | 3,000 |
| Writes per minute | 120 | 600 |
| Requests in progress | 50 | 250 |
| Exploit/injection probes (10 min) | 3 | 15 |
| 404s (10 min) | 200 | 1,000 |
| Failed logins (10 min) | 30 | 150 |

A person clicking through the console, even quickly, stays far below these; a
runaway script or someone abusing a stolen session does not. Past them the
account is throttled, then blocked, with the same escalation as anyone else,
and the alert names the account and the address it came from.

Two things follow from counting accounts rather than addresses:

* an admin on a shared network (a school, an office, mobile CGNAT) is not
  locked out by an IP block someone else on that network earned;
* a blocked admin account stays blocked from any address. The block page
  tells them so; another director can lift it from **Security Overview**
  (the row reads `admin account <id>`), or it lifts by itself (15 minutes for a
  first offence). If the owner is the only director and is blocked, waiting it
  out or setting `SECURITY_SHIELD=off` for a moment are the ways back in.

Admins are also never shed when the server is overloaded and are not affected
by under-attack mode, so you can always get in to deal with an incident.

## Script injection (XSS)

### The Content-Security-Policy

Every page carries a Content-Security-Policy whose `script-src` is
`'self' 'nonce-<random>'`, with a fresh, unguessable nonce on every response,
plus `script-src-attr 'none'` and `object-src 'none'`. The browser only runs:

* script files served from the site itself, and
* inline `<script>` blocks carrying that response's nonce.

Everything an attacker can inject into a page (a `<script>` tag in a dossier
title, an `<img onerror=…>`, an `onclick=` attribute, a `javascript:` link) has
no nonce, so the browser refuses to run it. This replaces the old
`'unsafe-inline'`, which let any injected script run.

**When you add an inline script**, give it the nonce or it will not run:

```html
<script nonce="{{ csp_nonce() }}">
  …
</script>
```

In HTML built in Python, use `security_shield.csp_nonce()`. Script files
(`<script src="/static/…">`) need nothing. Inline event handlers
(`onclick="…"`) never run; attach listeners from the script instead. A test
(`test_every_inline_script_in_the_templates_carries_the_nonce`) fails if a
template has an inline script without the nonce.

The persistent shell (`static/js/persistent_shell.js`, which swaps the landing
pages without a full reload) runs a fetched page's inline scripts only if they
carry the nonce from that response's own policy, so script injected into a
fetched page is dropped rather than run.

Styles may still be inline (`style-src 'unsafe-inline'`): injected CSS cannot
run code.

### Violation reports

Browsers report what the policy refused to `/csp-report`. Script, plugin,
`<base>` and form-target violations appear in the Security Overview incident
list as *Browser refused to run …* with the page and a sample of the script.
They are not sent to Discord: browser extensions inject scripts too and would
make it noisy. Several reports for one page and one script usually mean
someone found a way to inject markup there, so look at that page's output.

### Other layers

* Templates are auto-escaped, and the HTML built in Python escapes what it
  inserts.
* URLs carrying injection payloads are refused and count towards a block (see
  the table above). Only the path and query string are checked, never request
  bodies: writing about `<script>` in a dossier or a chat message is fine.
* Uploaded images and soundtracks are only ever served as images or audio, so
  an uploaded file cannot be turned into a page or a script on our origin.

## Floods and DDoS

* **Per-client budgets** (above) stop a single client.
* **Requests in progress** are capped per client, so a pile of deliberately
  slow requests cannot tie the server up the way a flood would. Event streams
  stop counting once they start answering.
* **Load shedding**: past 1,000 requests in progress site-wide, anonymous
  requests get `503 Server busy` (with `Retry-After`) while admins are still
  served, and a critical alert goes out.
* **Under-attack mode** switches on by itself when traffic surges (6,000
  requests a minute site-wide), when 20 or more clients hit limits within 10
  minutes, or when the server sheds load. For 10 minutes after the last
  trigger, anonymous visitors get half the normal limits, and data-centre, VPN
  and Tor addresses a quarter. That is still far above what a person browsing
  needs. Directors can also switch it on for 30 minutes to 24 hours from
  **Security Overview**, or off again.

What it can't do: the shield runs inside the app, so it stops abusive clients
cheaply but can't absorb a volumetric DDoS. That has to be dropped before it
reaches Railway. Turn on Cloudflare's DDoS protection and add a Cloudflare
rate-limiting rule as an outer layer; the shield keeps working behind it.

## Rotating addresses

An attacker switching addresses gets a fresh per-IP budget each time, so:

* IPv6 is counted per /64 (see above), the block a single connection gets;
* neighbouring addresses share a **network budget** (IPv4 /24, IPv6 /48) of 8
  per-IP budgets; past twice that, the whole network is blocked;
* in under-attack mode, data-centre, VPN and Tor addresses (the lists ZETA's
  VPN ban already downloads daily) get the tightest limits, since rented
  proxies are where rotating attacks come from;
* directors can block a whole network by hand, as CIDR (`203.0.113.0/24`, at
  most a /16 for IPv4 or a /32 for IPv6).

A botnet spread across many unrelated networks still only shows up through
the site-wide alerts and the tightened limits of under-attack mode; that kind
of attack is what the Cloudflare layer above is for.

## Logins and stolen sessions

### Failed logins

Sign-in to the website is through Discord, and every password or token check
arrives as an `Authorization` header (HTTP Basic, API tokens), a `?token=`
query parameter (event streams, websockets) or a websocket handshake carrying
one. All of these count: 30 failures in 10 minutes blocks the client. Operator
passwords are checked by the Discord bot, which has its own lockout.

### Stolen sessions

The session cookie is tied to the browser it was first used from (its
user-agent with version numbers removed, so browser updates are fine). The
binding is made on the sign-in response itself. If the cookie turns up in a
different browser or a script, the session is signed out on the spot and the
incident is logged. For an admin's session it is a critical alert: *Signed out
admin … their session cookie was sent from a different browser*. The real
admin just signs in again.

A user who switches their browser's "request desktop site" setting, or changes
browsers in a way that changes the user-agent, is signed out once and simply
signs in again.

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

Every block, surge, overload, distributed attack, admin session caught in
another browser and AI-budget exhaustion is:

1. logged (`Security shield: …`, at ERROR for critical incidents);
2. added to the director's activity feed as a **Security Alert** (live on the
   Security Overview page);
3. posted to Discord if one of these is set:
   * `SECURITY_ALERT_WEBHOOK_URL`: a Discord channel webhook URL, or
   * `SECURITY_ALERT_CHANNEL_ID`: a channel the bot can post in.

   `SECURITY_ALERT_MENTION` (for example `<@&123456789>`) is prepended to
   critical alerts to ping a role. Alerts are capped at 10 per 5 minutes; the
   rest are summarised so an attack can't flood the channel.

Throttling, CSP violation reports and member sessions caught in another
browser are logged and listed on the Security Overview but not sent to Discord.

## Director controls

**Director → Security Overview → Automated Defences** shows the shield status,
whether under-attack mode is on (and for how long), requests per minute and in
progress, every block (IP, network or admin account, with reason, time left and
hits since the block) and recent incidents. Directors can:

* lift any block, including an admin account's;
* block an IP or a network by hand for 1 hour to 30 days;
* switch under-attack mode on for 30 minutes to 24 hours, or off.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `SECURITY_SHIELD` | `on` | `off` disables rate limiting, blocking and session binding entirely |
| `SECURITY_AUTO_BLOCK` | `on` | `off`: throttle and alert, but never block automatically |
| `SECURITY_REQUESTS_PER_MINUTE` | 600 | Per-IP request budget |
| `SECURITY_WRITES_PER_MINUTE` | 120 | Per-IP write budget |
| `SECURITY_ASSETS_PER_MINUTE` | 2400 | Per-IP static-file budget |
| `SECURITY_ADMIN_LIMIT_FACTOR` | 5 | Admin limits as a multiple of the above (at least 1) |
| `SECURITY_NETWORK_FACTOR` | 8 | One network's (IPv4 /24, IPv6 /48) budget, in per-IP budgets |
| `SECURITY_MAX_PENDING_PER_IP` | 50 | Requests one client may have in progress |
| `SECURITY_MAX_PENDING` | 1000 | Requests in progress site-wide before anonymous ones are shed |
| `SECURITY_UNDER_ATTACK_FACTOR` | 0.5 | Share of the normal limits anonymous visitors get under attack |
| `SECURITY_HOSTING_FACTOR` | 0.25 | Share data-centre, VPN and Tor addresses get under attack |
| `SECURITY_UNDER_ATTACK_MINUTES` | 10 | How long automatic under-attack mode lasts after the last trigger |
| `SECURITY_FAILED_LOGIN_LIMIT` | 30 | Failed logins per 10 minutes before a block |
| `SECURITY_NOT_FOUND_LIMIT` | 200 | 404s per 10 minutes before a block |
| `SECURITY_PROBE_LIMIT` | 3 | Exploit-path and injection requests per 10 minutes before a block |
| `SECURITY_SURGE_ALERT_PER_MINUTE` | 6000 | Site-wide requests per minute that raise an alert |
| `SECURITY_SURGE_ALERT_IPS` | 20 | Distinct throttled clients (10 min) that raise an alert |
| `SECURITY_MAX_BODY_MB` / `SECURITY_MAX_UPLOAD_MB` | 8 / 51 | Request body caps (uploads leave room for 50 MB Project ZETA files) |
| `SECURITY_ALLOWLIST` | | Comma-separated IPs/CIDRs never limited (admins are still counted) |
| `SECURITY_CLIENT_IP_HEADER` | | Trust this one header for the client IP |
| `SECURITY_TRUSTED_PROXIES` | | Extra proxy CIDRs to skip in `X-Forwarded-For` |
| `ALICE_DAILY_COMMANDS_PER_USER` / `ALICE_DAILY_COMMANDS_TOTAL` | 150 / 1500 | Daily caps on paid A.L.I.C.E. model calls |

## Limits of the design

* **Volumetric DDoS** needs the Cloudflare layer described above.
* **The injection filter** only reads URLs. It catches scanners and casual
  attempts; the Content-Security-Policy is what actually stops injected
  scripts from running.
* **One process.** Counters live in memory. The site runs as one process on
  one Railway replica, so that is every request. If it is ever scaled to
  several replicas, each keeps its own budgets and only picks up the others'
  blocks when it restarts.

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

Second pass:

* **Admins were exempt** from the shield, so a stolen admin session or a
  runaway script on an admin account was never limited. Admins are now
  counted per account at higher limits.
* **Inline scripts** needed `'unsafe-inline'`, so the policy gave no protection
  against injected script. Inline scripts now carry a per-response nonce and
  `'unsafe-inline'` is gone; violations are reported.
* **Uploaded media** was served with whatever content type it was stored with;
  now only as images or audio.
* **Floods**: added caps on requests in progress, load shedding and
  under-attack mode.
* **Rotating addresses**: IPv6 counted per /64, network budgets and blocks.
* **Tokens in URLs and websocket handshakes** were not counted as failed
  logins; now they are.
* **Session cookies** worked from any browser; now they are tied to the one
  they were issued to.

Still worth doing:

* Set long random `SESSION_SECRET` and `JWT_SECRET` values in Railway if they
  aren't already. Without them sessions and tokens reset on every restart, and
  a short session secret can be brute-forced to forge an admin session.
* Several pages load Google Fonts, which the Content-Security-Policy has always
  blocked (`style-src` and `font-src` don't list Google), so those pages fall
  back to system fonts. Either self-host the fonts under `/static` or add
  `https://fonts.googleapis.com` to `style-src` and `https://fonts.gstatic.com`
  to a `font-src`.
* The Discord OAuth access token is kept in the signed (but not encrypted)
  session cookie. Only its owner can read it, but it would be safer server-side.
