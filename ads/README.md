# Advertiser content

Keep campaign text in [`ads.json`](ads.json) and campaign image files in [`images/`](images/). Ads are organized by news category: each category has its own list, so an advertiser can target only the category it belongs to.

## Categories

`top`, `nigeria`, `world`, `entertainment`, `sports`, `technology`, `science`, `business`, `gaming`, `fashion`, and `other`.

## Add a campaign

Add a campaign object to the appropriate category array in `ads.json`:

```json
{
  "id": "example-campaign",
  "enabled": false,
  "advertiser": "Advertiser name",
  "headline": "Campaign headline",
  "body": "Short description shown in the sponsored card.",
  "image": "ads/images/example-campaign.jpg",
  "destinationUrl": "https://example.com/"
}
```

For example, a sports advertiser's campaign belongs under `categories.sports`; it will not be mixed into the technology or other category lists.

- `id`: unique campaign identifier.
- `enabled`: set to `true` when the campaign is approved to display. Keep campaigns disabled until their details and destination are reviewed.
- `advertiser`: name displayed with the ad.
- `headline`: ad heading.
- `body`: short descriptive text.
- `image`: path to an image committed in this repository. Use a relative path from the repository root.
- `destinationUrl`: full HTTPS landing-page URL.

Use valid JSON (double quotes, commas between fields, no trailing commas). Keep ad content clearly identifiable as sponsored. The category lists are configuration only; the site still needs ad-rendering code to display them. This folder does not provide advertiser accounts, approvals, payments, or analytics.
