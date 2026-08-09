# Connecting a new niche's platform accounts

Everything here is written from real mistakes made setting up Barber -- follow this order
and you should skip every dead end we hit the first time. Apps/projects listed as "reusable"
already exist and don't need to be recreated per niche; only the *account connections* and
*tokens* are new per niche.

Scripts referenced below live in `scripts/` and are run locally:
`.venv/bin/python scripts/<name>.py`.

## Before starting

- The niche's Instagram, Facebook Page, TikTok, and YouTube accounts must already exist as
  real accounts (create them first, outside of any of this).
- Have `assets/avatars/<Niche>/marketing/` populated with real images and a `manifest.yaml`
  before wiring credentials -- no point connecting accounts you can't post to yet.

---

## Instagram (via Instagram Login -- NOT Facebook Login)

**Reusable**: the Meta app ("Auto-posting").

Facebook Login and Instagram Login are two separate Meta identity systems that do not share
data. The classic `Page.instagram_business_account` Graph API field **only ever resolves for
a Facebook-Login-based connection** -- if the account was connected via Instagram Login
(which is the path below, and the simpler one), that field stays empty forever. Don't chase
it; use the Instagram Login path's own account list instead.

1. Meta app dashboard -> **Instagram API** -> **"API setup with Instagram login"**.
2. Under that page, add the niche's Instagram account (via "Add account"). It'll show up in
   a list with its real Instagram-scoped user ID directly (this **is** the ID needed for
   `business_account_id` in `niches.yaml` -- no separate lookup required).
3. Click **"Generate token"** next to that account -> copy the long-lived (~60 day) access
   token shown. This is simpler than the OAuth code-exchange flow (`scripts/
   verify_instagram_login.py` exists as a fallback but wasn't actually needed).
4. Save as `ig_access_token` for this niche.

**Gotcha**: double-check the correct Meta app is selected before doing anything here --
mixing it up with an unrelated Meta app (e.g. an existing messaging app) produces confusing
permission errors that look like a completely different problem.

**API base for Instagram Login tokens**: `graph.instagram.com`, not `graph.facebook.com`.

---

## Facebook (classic Facebook Login, Page token)

**Reusable**: same Meta app ("Auto-posting").

1. `developers.facebook.com/tools/explorer` -> select the **"Auto-posting"** app.
2. **Generate Access Token**, with permissions: `pages_show_list`, `pages_read_engagement`,
   `pages_manage_posts`, **and `business_management`** (see gotcha below -- don't skip this
   one even though it looks unrelated).
3. Run a `me/accounts` GET request. If the Page you need isn't in the result:
   - Go to `facebook.com` -> Settings & Privacy -> Settings -> **Business Integrations** ->
     find "Auto-posting" -> **Remove** (only remove the row for this app -- don't touch
     unrelated connected apps, e.g. any Developer Tools MCP connection).
   - Go back to the Explorer, **Generate Access Token** again. This time you should see a
     real consent flow: "Continue as [You]?" -> "Choose the Pages you want Auto-posting to
     access" -> pick **"Opt in to all current and future Pages"** -> review & confirm the
     permission list -> Save.
   - Re-run `me/accounts` -- the Page should now appear with its own `access_token` field.
4. That token is **short-lived**. Extend it: click the small "i" icon next to the Access
   Token field -> **"Open in Access Token Tool"** -> **"Extend Access Token"**. Use the
   resulting long-lived token (valid ~60 days) as `meta_access_token`.

**Gotcha #1**: `me/accounts` can come back empty even with seemingly-correct permissions if
the page-selection consent screen never actually appeared (Facebook silently reuses old
settings that granted zero Pages). The remove-and-regenerate step above forces a fresh
consent flow.

**Gotcha #2**: `me/accounts` can *still* come back empty after that if the Page has been
pulled under a Meta Business Portfolio (a 2026 Meta rollout affecting most Pages) --
`business_management` permission is required to see Portfolio-owned Pages, `pages_show_list`
alone is not enough.

**Note**: Facebook posts can never get audio added after publishing, and only via the mobile
app before publishing -- not something the API can do. Not relevant for photo carousels.

---

## TikTok

**Reusable**: the TikTok app ("auto-post").

New apps default into **Sandbox** mode, which is correct for our use case (not something to
route around) -- our publishing uses `post_mode=MEDIA_UPLOAD` (drafts/inbox), which doesn't
need App Review, and Sandbox is exactly the environment for testing that without review.

1. On the app's page, use the **Production | Sandbox** toggle near the app name -> switch to
   Sandbox. If no sandbox exists yet, **Create Sandbox**.
2. Inside the sandbox (separate config from production -- add these again even if already
   set on the production side):
   - **Add products**: Login Kit, Content Posting API.
   - Login Kit's **Redirect URI**: must be a real `https://` domain you own --
     **TikTok rejects `localhost` outright**, unlike Meta/Google. We use `https://bizyr.co/`
     purely as a landing spot to read the `code=` value out of the browser's address bar;
     no real page needs to exist there.
   - **Scopes**: `video.upload`/`video.publish` show up automatically once Content Posting
     API is added ("Included in Content Posting API") -- no need to manually add them via
     the scope picker; don't add unrelated Login-Kit-only scopes like `user.info.profile`.
   - **Sandbox settings -> Target Users**: add the niche's TikTok account (up to 10 per
     sandbox). Only accounts added here can complete OAuth against this app while in
     Sandbox.
3. Get an authorization code:
   `https://www.tiktok.com/v2/auth/authorize/?client_key=<key>&scope=user.info.basic,video.upload&response_type=code&redirect_uri=https%3A%2F%2Fbizyr.co%2F&state=xyz123`
   -- open in a browser, log in as the target account, approve. Copy the `code=` value from
   the resulting redirect URL (stop before `&state`).
   - **Shell gotcha**: if the code contains `!`, wrap it in **single quotes** when using it
     in a terminal command -- zsh treats `!` as history expansion even inside double quotes.
4. Exchange the code: `scripts/exchange_tiktok_code.py "<code>"` (needs
   `TIKTOK_CLIENT_KEY`/`TIKTOK_CLIENT_SECRET` exported first). Save the resulting
   `access_token` (`tiktok_access_token`) and `refresh_token` (`tiktok_refresh_token`, not
   consumed by the pipeline yet but worth saving).

### Domain verification (one-time per hosting URL, likely already done -- check first)

Photo/carousel posts only support `PULL_FROM_URL` (not `FILE_UPLOAD`, which is video-only),
and TikTok requires the hosting domain/URL-prefix to be verified before it'll fetch from it.
This project's hosting URL prefix (`https://raw.githubusercontent.com/bricksx11/the-network/render-scratch/`)
is likely **already verified** -- check the app's "URL properties" panel first before
redoing this.

If it's ever not verified (e.g. a new repo): Content Posting API section -> "Verify domains"
-> Verify -> **URL prefix** (not "Domain" -- we don't own all of raw.githubusercontent.com)
-> enter the exact prefix -> download the signature `.txt` file -> drop it into
`assets/verification-files/` in the repo (it gets auto-included in every scratch-branch push
via `hosting.py`, since that branch is otherwise wiped clean on every publish) -> commit ->
click Verify in the dashboard.

**Gotcha**: this whole scheme requires the repo to be **public** -- `raw.githubusercontent.com`
404s on unauthenticated requests to a private repo (confirmed by testing with vs. without a
GitHub token), so TikTok (and any other external fetcher) can never reach a private repo's
files no matter how correct everything else is.

### Format and status gotchas

- TikTok **rejects PNG outright** for photo posts (`file_format_check_failed`) -- JPEG/WEBP
  only. Already fixed in `render/carousel.py` (renders JPEG universally).
- A `publish_id` from the init call is **not proof of success** -- the actual pull-from-URL
  and processing happens async. Always poll `check_publish_status`/`wait_for_publish_complete`
  (already wired into `orchestrator.py`). Use `scripts/check_tiktok_publish_status.py
  "<publish_id>"` to check manually.
- The real terminal **success** status for `post_mode=MEDIA_UPLOAD` is `SEND_TO_USER_INBOX`,
  not `PUBLISH_COMPLETE` (that name is for `DIRECT_POST`, which this project never uses).
  Already fixed in `publish/tiktok.py`.
- Delivered content shows up as an **inbox notification** inside the TikTok app (tap the
  inbox/messages icon), not the regular Drafts folder.
- TikTok auto-suggests a sound when you open a photo draft to edit ("Auto-Generated Sound")
  -- that's TikTok's own feature, nothing this project's API calls do.

---

## YouTube

**Reusable**: the Google Cloud project, OAuth consent screen, OAuth client (Desktop app type).

1. OAuth consent screen -> **Audience** tab -> add the niche's channel-owning Google account
   as a **Test user** (required while the app is in Testing mode -- that account can't
   complete consent otherwise).
2. Mint a refresh token locally:
   `scripts/mint_youtube_refresh_token.py "<path to client_secret_....json>"` -- opens a
   browser, log in as that Google account, approve. The refresh token prints to your
   terminal at the end; it's never sent anywhere else.
3. Save `youtube.refresh_token`, plus `youtube.client_id`/`youtube.client_secret` from the
   same `client_secret_*.json` file (the `client_id` isn't actually sensitive; it's public in
   the OAuth URL itself).

Uploads always land as `privacyStatus: private` -- nothing goes public until manually
published in Studio. Add real audio there too: **Studio -> Content -> edit icon -> Editor ->
Audio tab** -> pick a track from YouTube's own Audio Library -> Add. Works on an
already-uploaded (even still-private) video, no re-upload needed -- but only with tracks from
YouTube's own library, not arbitrary external files.

Per-platform CTA (e.g. "Link in bio" -- YouTube has no DM/comment-bait culture) is set via
`cta_override` under that niche's `youtube` block in `niches.yaml`.

---

## Assembling and pushing the final secret

Once every value above exists, put them in a plain-text scratch file (never committed, never
pasted into chat) shaped like:

```
ig_access_token = ...
meta_access_token (Page token) = ...
tiktok_access_token = ...
tiktok_refresh_token = ...
youtube_refresh_token = ...
youtube_client_id = ...
youtube_client_secret = ...
```

Then, from the repo root:

```
.venv/bin/python scripts/build_niche_creds.py "<path to the scratch file>" \
  | gh secret set NICHE_CREDS__<NICHE> --repo bricksx11/the-network
```

That builds the exact JSON shape `src/credentials.py` expects and pushes it straight to
GitHub Secrets -- nothing gets manually retyped, nothing passes through chat.

Finally, add the niche's block to `config/niches.yaml` (copy Barber's block, update
`image_dir`, `trend_seed_keyword`, and the four platform account IDs) and set
`enabled: true` per platform only once you're actually ready for that platform to go live.

---

## Cross-cutting lessons (not platform-specific)

- **GitHub Actions permissions**: a reusable workflow's `permissions:` can only be
  *downgraded* by its caller, never elevated -- and a repo's own default token permission
  (often read-only on new repos) caps everything above it. Both the reusable workflow *and*
  every top-level workflow that calls it need their own explicit `permissions: contents:
  write` if a job needs to push back to the repo (e.g. committing a run log).
- **`ubuntu-latest` runners don't ship `ffmpeg`** -- install it explicitly
  (`apt-get install -y ffmpeg`) before any rendering step.
- **zsh + `!`**: any token/code containing `!` needs single quotes in a terminal command, or
  zsh's history expansion mangles it.
- **`python scripts/foo.py` vs `python -m`**: running a script directly (not as a module)
  doesn't put the repo root on `sys.path`, so `from src...` imports fail unless the script
  adds a `sys.path.insert(0, ...)` shim itself (all scripts in `scripts/` already do this).
- **Never trust a platform's initial "accepted" response as proof of success** -- TikTok's
  init call in particular can look fine while the real async processing fails silently; only
  a polled terminal status is proof.
