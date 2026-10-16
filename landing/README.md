# emvoox.com landing page

Static site for **emvoox.com** on DreamHost shared hosting. It needs no build step: plain HTML, CSS and JavaScript, and
one PHP file for the contact form. Layout follows v1ron.com; colours and type follow Emvoox Studio
(`web/app/globals.css`): navy `#284979`, gold `#c99a2e`, Be Vietnam Pro, Noto Serif, JetBrains Mono, with a light and a
dark theme.

```
index.html            the page (English copy lives here)
assets/css/site.css   all styles; tokens at the top (light) and html[data-theme="dark"]
assets/js/i18n.js     Vietnamese copy, keyed by data-i18n / data-i18n-ph / data-i18n-aria / data-i18n-content
assets/js/i18n-zh.js  Simplified Chinese copy, same keys (Chinese fonts load only when 中文 is chosen)
assets/js/site.js     theme, language, nav, reveal, pill tabs, agent stage, audience gallery, pattern fields, FAQ,
                      count-up figures, voice auditions, contact form
assets/img/           logo marks, favicon, og-image.png (1200x630 share card)
assets/audio/         4 voice auditions (Linh, Minh Khôi, Ngân, Dương) from data/assets/previews/*_gemini.wav
contact.php           form handler (PHP mail): same field rules as the page, honeypot, per-IP rate limit, JSON reply
.htaccess             HTTPS + bare-domain redirect, security headers, gzip, caching
robots.txt, sitemap.xml
```

## Preview locally

```bash
cd landing && python3 -m http.server 8811     # http://127.0.0.1:8811  (?lang=vi Vietnamese, ?lang=zh Chinese)
```

The form cannot send locally (no PHP). It then offers the visitor a pre-filled email link instead.

## Language and theme

English is the markup and the default language; dark is the default theme. A visitor switches with `?lang=vi` /
`?lang=zh` or the EN / VI / 中文 switch and the theme button, and both choices are remembered in `localStorage`. To change copy, edit the English in
`index.html` and the same key in **both** `assets/js/i18n.js` (Vietnamese) and `assets/js/i18n-zh.js` (Chinese).
Form error messages and the "Other" country-code option are read by `site.js` through the same dictionaries
(`ct.e.*`, `ct.o.cc.other`). Every `data-i18n` key must exist in both files:

```bash
python3 - <<'EOF'
import re
h=open('index.html',encoding='utf-8').read()
k=set(re.findall(r'data-i18n(?:-ph|-aria|-content)?="([^"]+)"',h))
for f in ('assets/js/i18n.js','assets/js/i18n-zh.js'):
    v=set(re.findall(r'^\s*"([^"]+)":',open(f,encoding='utf-8').read(),re.M))
    print(f, 'missing:', sorted(k-v) or 'none')
EOF
```

SEO: each language has its own URL (`/`, `/?lang=vi`, `/?lang=zh`) declared with `hreflang` in `<head>` and in
`sitemap.xml`; `site.js` points the canonical link at the active language. The translation is applied by JavaScript,
which Google renders. Search engines that do not run JavaScript only see the English text.

## Contact form rules

Checked in the browser (`site.js`) and again in `contact.php`. The error appears under the field:
- name: required, at least 2 characters
- email: required, must look like an email
- phone: required, 6 to 14 digits (spaces, dots, dashes and brackets are allowed), plus a country code from the list or
  typed under "Other"
- message: required, at least 10 characters

The email you receive shows the phone as `+<code> <number>`.

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
  has it as Phase 3 (Short films with Visual IPs), the Character IP tab says "as the short-drama pipeline lands", and the four visual agents are
  marked "next". Keep those markers until the image pipeline runs.
- **Fine-tuning strip** (end of the Agents section) is marked "in progress": no agent is fine-tuned yet. It states the
  intent (tune on our own runs, replace an agent only when it scores better, adapt to each user's style and
  preferences, which depends on the long-term memory planned for Phase 5) and the rules (consent and licence for
  voices and likenesses, AI disclosure, Vietnamese personal-data law, human approval). Keep the marker until a tuned
  agent is in use, and have the legal wording checked before naming specific laws.
- **"8 AI agents"** counts the Producer plus the 7 pipeline agents in `emvoox/agents/` (research, script, casting,
  director, sound, QA, publisher).
- **Voice auditions** (Character IP tab) use the IPs' current engine voices (Gemini prebuilt), not cloned signature
  voices, and the note under the roster says so. No episode is published: every produced episode is still waiting at
  the human approval gate. Once an episode is approved, an excerpt can go in `assets/audio/`.
- **Character IP names and personas** come from `data/assets/voice_registry.json` (7 IPs). The brand book plans 1–2
  lead actors for the pilot, so trim the roster if that is the public line.
- **Sample title** in the hero and the chat mockup, "Ván Cờ Tái Sinh: Sự Trở Lại Của Đế Vương" ("Rebirth Gambit:
  Return of the Emperor", 《重生棋局：帝王归来》), is illustrative, not a produced series.
- **Screen mockups** (hero card, Producer chat, feature tiles, agent stage, Mặc Khải card) follow the page language
  through `mk.*` keys. Character names, the Mặc Khải name and technical ids stay as they are. The forms-of-address tile
  keeps its Vietnamese lines on purpose and adds an English or Chinese gloss (`mk.gloss.*`, empty in Vietnamese).
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
