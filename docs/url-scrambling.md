# Scrambled URLs

Every page, API endpoint and static file can be served under an opaque address
instead of its readable one, so search-engine dorks (`inurl:admin`,
`inurl:director`) and scanners probing for `/admin`, `/api/...` or `/static/...`
find nothing. With it on, `/director` answers 404 and the director console lives
at something like `/lyeuakv6bnxe`.

This hides the site's layout; it does not replace sign-in. Every page keeps its
existing access checks.

## Turning it on

1. Generate a secret: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Add it to the Railway service as `URL_SCRAMBLE_SECRET` and redeploy.
3. Find the new addresses in the deploy logs (`URL scrambling is on ... Entry
   points: /dashboard -> ...`), or start from the landing page: every link on the
   site is rewritten, so normal navigation keeps working.

To print the address of any page: `URL_SCRAMBLE_SECRET=... python url_scramble.py /director /admin`.

Addresses depend only on the secret, so they stay the same across redeploys.
Changing the secret moves every address at once (old bookmarks then 404);
removing it switches back to readable URLs.

## What stays readable

- `/` (the landing page)
- `/health` (Railway health check)
- `/auth/callback` and `/callback` (registered with Discord for login)
- `/robots.txt`

## After switching it on

- Bookmarks to old addresses stop working; re-bookmark from the site.
- Discord messages the bot posted earlier still link to the readable
  `/spectre/archive`; refreshing the archive menu posts the new address.

## Search engines

Independently of scrambling, every response except the landing page carries
`X-Robots-Tag: noindex, nofollow, noarchive`, and `/robots.txt` only allows the
landing page. The API docs (`/docs`, `/openapi.json`) are served to signed-in
portal admins only.
