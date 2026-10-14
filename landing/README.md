# emvoox.com landing page

Static site for **emvoox.com** on DreamHost shared hosting. It needs no build step: plain HTML, CSS and JavaScript, and
one PHP file for the contact form. Layout follows v1ron.com; colours and type follow Emvoox Studio
(`web/app/globals.css`): navy `#284979`, gold `#c99a2e`, Be Vietnam Pro, Noto Serif, JetBrains Mono, with a light and a
dark theme.

```
index.html            the page (English copy lives here)
assets/css/site.css   all styles; tokens at the top (light) and html[data-theme="dark"]
assets/js/i18n.js     Vietnamese copy, keyed by data-i18n / data-i18n-ph / data-i18n-aria / data-i18n-content
assets/js/site.js     theme, language, nav, reveal, product tabs, voice auditions, contact form
assets/img/           logo marks, favicon, og-image.png (1200x630 share card)
assets/audio/         4 voice auditions (Linh, Minh Khôi, Ngân, Dương) from data/assets/previews/*_gemini.wav
contact.php           form handler (PHP mail), honeypot and per-IP rate limit, JSON reply
.htaccess             HTTPS + bare-domain redirect, security headers, gzip, caching
robots.txt, sitemap.xml
```

## Preview locally

```bash
cd landing && python3 -m http.server 8811     # http://127.0.0.1:8811  (?lang=vi for Vietnamese)
```

The form cannot send locally (no PHP). It then offers the visitor a pre-filled email link instead.

## Language and theme

English is the markup. Vietnamese is chosen when the browser language is `vi`, by `?lang=vi`, or by the EN / VI
switch, and is remembered in `localStorage`. To change copy, edit the English in `index.html` and the same key in
`assets/js/i18n.js`. Every `data-i18n` key must exist in `i18n.js`:

```bash
python3 - <<'EOF'
import re
h=open('index.html',encoding='utf-8').read(); j=open('assets/js/i18n.js',encoding='utf-8').read()
k=set(re.findall(r'data-i18n(?:-ph|-aria|-content)?="([^"]+)"',h)); v=set(re.findall(r'^\s*"([^"]+)":',j,re.M))
print('missing in i18n.js:', sorted(k-v) or 'none')
EOF
```

When you change CSS or JS, bump the `?v=` query on its `<link>` / `<script>` in `index.html` (files are cached 30 days).

## Deploy to DreamHost

State on 2026-10-14: DNS and mail (MX) for emvoox.com are on DreamHost, HTTPS is active, and the site shows
DreamHost's "almost here" placeholder. SSH user: `emvooxmaster@iad1-shared-e1-32.dreamhost.com`.

1. **Panel:**
   - Under Websites → Manage, set PHP to 8.x for emvoox.com.
   - Mail: the form sends from and to `dhp@emvoox.com` (a DreamHost mailbox). DreamHost only sends from addresses on
     domains it hosts. To use another address (for example a shared `hello@`), change `$TO` / `$FROM` at the top of
     `contact.php` and the address in `index.html`.
2. **SSH key, once:** run `ssh-keygen -t ed25519`, then `ssh-copy-id emvooxmaster@iad1-shared-e1-32.dreamhost.com`.
   Then add the following to `~/.ssh/config`:

   ```
   Host emvoox
     HostName iad1-shared-e1-32.dreamhost.com
     User emvooxmaster
     IdentityFile ~/.ssh/id_ed25519
   ```
3. **Look before uploading:** `ssh emvoox 'ls -la ~ ~/emvoox.com'`. The web directory is usually `~/emvoox.com`.
   If DreamHost's placeholder file (for example `quickstart.html`) is there, remove it after the upload.
4. **Upload:**
   - `scripts/deploy_landing.sh` (dry run). Check the list of files, then run `scripts/deploy_landing.sh --live`.
   - The script uses rsync. It uploads `.htaccess` and skips this README. It never deletes files on the server.
5. **Check:**
   - Open `https://emvoox.com` and `https://emvoox.com/?lang=vi`, play an audition, and send a test message
     through the form.
   - `curl -I https://emvoox.com/README.md` should return 403 or 404.
   - PHP and mail errors are in `~/logs/emvoox.com/https/error.log` on the server.

Later updates: edit locally, bump `?v=`, then run `scripts/deploy_landing.sh --live` again.

## Before going live (content to confirm)

- **Contact:** the page shows `dhp@emvoox.com`, and the form delivers there. The location shows only "Ho Chi Minh City, Vietnam".
- **Company name:** the page never calls Emvoox a company, and the footer reads "© Emvoox". The team doc says the
  legal entity is not yet confirmed.
- **Positioning:** the page leads with the two differentiators: the agentic pipeline (Producer + 7 agents, "Agents"
  section) and Character IPs (voice + image). It also presents the short-drama pipeline (audio + image) as next.
- **Image side of Character IPs:** visual identity is not built yet. The page says so where it matters: the roadmap
  has it as Phase 2, the Character IP tab says "as the short-drama pipeline lands", and the four visual agents are
  marked "next". Keep those markers until the image pipeline runs.
- **"8 AI agents"** counts the Producer plus the 7 pipeline agents in `emvoox/agents/` (research, script, casting,
  director, sound, QA, publisher).
- **Voice auditions** (Character IP tab) use the IPs' current engine voices (Gemini prebuilt), not cloned signature
  voices, and the note under the roster says so. No episode is published: every produced episode is still waiting at
  the human approval gate. Once an episode is approved, an excerpt can go in `assets/audio/`.
- **Character IP names and personas** come from `data/assets/voice_registry.json` (7 IPs). The brand book plans 1–2
  lead actors for the pilot, so trim the roster if that is the public line.
- **Sample title** in the hero and the chat mockup, "Ván Cờ Tái Sinh: Sự Trở Lại Của Đế Vương", is illustrative,
  not a produced series.
- **Comparison table** uses generic categories (AI voice tools, generic AI content tools, traditional studio) from the
  technical map. It names no competitor.
- **Market figures:**
  - DataEye 95.37% and 7 of 10: DataEye 2025, as cited in the team doc.
  - 302 bn VND on 60-second drama apps in Vietnam, 2025: from the team's market research.
- **Claims left out on purpose:** the team flagged these as hypotheses, so they are not on the page:
  - 80–90% lower cost
  - under 24 hours per series
  - 1M followers
  - "100% consistency"
  - "5 people = a 50-person studio"
