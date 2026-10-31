# News Site V4 — scalable RSS aggregation

This version keeps the static website and GitHub Actions workflow, but replaces the hard-coded list of six feeds with `feeds.json`. The collector creates combined category feeds under `feeds/`.

## How to add sources

1. Open `feeds.json`.
2. Add an entry to `sources` with a readable `name`, the publisher's RSS/Atom `url`, a `category`, and `enabled: true`.
3. Commit and push the change to GitHub.
4. In GitHub, open **Actions → Update news → Run workflow** to test immediately. Otherwise, it runs on the 15-minute schedule.

Example:

```json
{
  "name": "Example Publisher",
  "url": "https://example.com/feed.xml",
  "category": "world",
  "enabled": true
}
```

Supported categories: `nigeria`, `world`, `entertainment`, `sports`, `technology`, `science`, `business` (shown on the site as “Business · Crypto & Banks”), `gaming`, `fashion`, `other`. The business category includes crypto-market and banking/business publishers such as CoinDesk, Cointelegraph, Decrypt, BBC Business, and Banking Dive. The `top` feed is generated automatically from all categories.

## Run locally

Requires Python 3.12+, `feedparser`, and Pillow:

```bash
python -m pip install feedparser Pillow
python scripts/fetch_news.py
```

## Notes and limitations

- There is no fixed source count in the configuration. Practical throughput is limited by GitHub Actions runtime, network access, feed publisher rate limits, and the size of generated files. The collector processes up to 100 recent entries per source per run and outputs up to 5,000 items per generated feed.
- Feeds may be unavailable, invalid, blocked, or temporarily empty. A failed source is logged and does not stop other sources. If every configured source fails, the job fails instead of replacing feeds with empty results.
- Articles are deduplicated by canonical URL and normalized title across sources. This is intentionally conservative and may merge two stories with identical titles.
- DailyPulse only publishes articles whose RSS/Atom entry includes an image URL. Articles without a feed-provided image are skipped by the collector and filtered in the browser, including older generated XML feeds.
- The website links to original articles and displays metadata/short summaries rather than copying full article text. Respect publisher terms, robots policies, copyright, and feed/API terms.
- GitHub Actions schedules are not guaranteed to start at the exact minute. GitHub Pages may also take time to publish a commit.
- Keep the repository public/private as desired, but do not put API keys or secrets in `feeds.json`.


## DailyPulse responsive interface

The homepage now uses the DailyPulse brand and a responsive layout: stacked image-led cards on phones and a two-column article-card grid on desktop/tablet widths. The RSS category filters, refresh button, local generated feeds, original publisher links, and automatic refresh remain in place.


### Image quality filtering

Stories are only published when the RSS item includes an accessible image at least 400×225 pixels. The collector checks image sharpness using a lightweight edge-based heuristic and skips images that appear too blurry, inaccessible, invalid, or too small. This is an automated image-quality heuristic, not an AI vision model; it may occasionally reject a valid image or miss subtle blur.

## Expanded sports and science sources

The feed configuration includes additional sports coverage (BBC Sport, Sky Sports, The Athletic, Bleacher Report, Formula 1, Yahoo Sports) and science/space coverage (Science.org, New Scientist, Phys.org, Quanta Magazine, BBC Science, NYT Science, ESA, NASA, Space.com). The collector continues to publish only entries whose image URL is present and whose image passes its availability, minimum-dimension, and sharpness checks. RSS providers may change feed endpoints or omit images, so the workflow can skip entries even from enabled sources.


## Reduced RSS collection

This configuration uses 20 selected RSS sources instead of 85 and schedules collection hourly (at minute 17). This reduces routine feed requests and workflow runs, but does not guarantee compliance with GitHub's Terms or explain/resolve any account suspension. Review GitHub's notice and contact Support for account-specific decisions.

The collector skips stories without a usable RSS image and applies a basic image-quality heuristic; it is not an AI vision model. RSS endpoints and image availability can change, so check workflow logs after restoring repository access.


## Image quality and source selection

- BBC RSS sources have been removed from this configuration because their thumbnails appeared blurry in the site.
- The collector checks for an image at least 400×225 pixels and applies a sharpness heuristic. Articles with no usable image are skipped.
- If an RSS entry supplies several image candidates, the collector prefers the largest one and tries alternatives when an image fails the checks.
- The sharpness check is a lightweight heuristic, not an AI vision model, so some images may still look soft. Feed endpoints and image quality should be verified in GitHub Actions after upload.


### Sports feed and article text

The Sky Sports Football source has been replaced with The Athletic Soccer RSS feed (`https://www.nytimes.com/athletic/rss/football/`). The collector now prefers the longest available RSS body/summary text (up to 3,000 characters) and keeps the headline. RSS publishers may provide only an excerpt, so full article body text cannot be guaranteed unless the publisher includes it in its feed.

## DailyPulse Assistant — Gemini API setup

The homepage includes the blue DailyPulse Assistant chat widget. It sends visitor questions to a small Cloudflare Worker backend. The Worker reads the **generated `feeds/top.xml` file** (the same aggregated news feed updated by the scheduled GitHub Actions workflow), supplies the latest 60 generated article records to Gemini, and instructs Gemini to answer current-news questions only from those records. Answers can include the original publisher links stored in the feed. The chatbot does not scrape publisher pages or invent links.

### 1. Deploy the private-key backend (Cloudflare Workers free plan)

1. Create/sign in to a Cloudflare account and open **Workers & Pages**.
2. Choose **Create application → Create Worker**, give it a name such as `dailypulse-assistant`, and deploy the starter Worker.
3. Open the Worker, choose **Edit code**, replace the starter code with the complete contents of `worker.js`, and deploy.
4. Open **Settings → Variables and Secrets** (the wording may vary) and add:
   - Secret: `GEMINI_API_KEY` — paste your Gemini API key here. Mark it as a **Secret**, not a plain-text variable.
   - Variable: `SITE_ORIGIN` — `https://onlyonedev8.github.io`
   - Variable: `NEWS_FEED_URL` — `https://onlyonedev8.github.io/online/feeds/top.xml`
   - Optional variable: `GEMINI_MODEL` — `gemini-2.5-flash`
5. Save/deploy the Worker again if Cloudflare requests it. Copy its public `workers.dev` address; it will look like `https://dailypulse-assistant.<your-subdomain>.workers.dev`.

**Important:** The Gemini key belongs only in the Cloudflare Worker secret. Do not put it in `index.html`, `feeds.json`, GitHub Pages files, or any public repository file. If the key was ever committed publicly, revoke it in Google AI Studio and create a replacement.

### 2. Connect the homepage to the Worker

1. Open `index.html`.
2. Find `const CHAT_API_URL =` near the bottom of the file.
3. Replace the example URL with your Worker URL followed by `/chat`, for example:

   `const CHAT_API_URL = 'https://dailypulse-assistant.example.workers.dev/chat';`

4. Save and push the updated site files to GitHub. Keep the rest of the URL and `/chat` path intact.

### 3. Verify it

1. In GitHub, open **Actions → Update news** and run the workflow, or wait for its hourly schedule. Confirm that the run commits updated files in `feeds/`.
2. Open `https://onlyonedev8.github.io/online/feeds/top.xml` in a browser and confirm it contains recent `<item>` records.
3. Open DailyPulse, tap the assistant icon, and ask: “What are the latest headlines?” Try asking for a specific story and confirm the answer includes the article's original feed link.

### How feed-grounded answers work

- The Worker fetches the latest generated `top.xml` feed for each chat request; it does not use a hard-coded sample of stories.
- The generated feed includes each story's title, publisher, category, publication date, description, and canonical original link.
- The Worker passes up to 60 recent feed items to Gemini and explicitly tells it not to invent news, scores, dates, facts, or URLs. If the requested information is not in the feed, it should say so.
- When the cron job updates the generated feed files, later chatbot requests use the new feed data. GitHub Pages publishing/cache delay may mean a short wait after a workflow completes.
- The frontend sends recent conversation turns so follow-up questions have context. It does not include a file-attachment control.

### Security and free-tier notes

- The browser calls your Worker, not Google's Gemini endpoint directly, so the API key is not exposed to visitors.
- The Worker restricts browser origins to `SITE_ORIGIN` (plus localhost development origins). If you move DailyPulse to a custom domain, update `SITE_ORIGIN` and redeploy.
- Free plans and Gemini API free-tier quotas have limits and can change. This setup is not unlimited or guaranteed to remain free; monitor Cloudflare and Google usage. Consider adding rate limiting before promoting the chatbot widely.
- If your deployed site uses a different feed URL or GitHub Pages base path, change `NEWS_FEED_URL` to the exact publicly accessible `top.xml` URL.
