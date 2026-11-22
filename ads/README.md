# Advertiser content

Keep campaign text in [`ads.json`](ads.json) and campaign image files in [`images/`](images/).

## Add a campaign

Add an object to the `ads` array in `ads.json`:

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

- `id`: unique campaign identifier.
- `enabled`: set to `true` when the campaign is approved to display. New examples should remain disabled until their details and destination are reviewed.
- `advertiser`: name displayed with the ad.
- `headline`: ad heading.
- `body`: short descriptive text.
- `image`: path to an image committed in this repository. Use a relative path from the repository root.
- `destinationUrl`: full HTTPS landing-page URL.

Use valid JSON (double quotes, commas between fields, no trailing commas). Keep ad content clearly identifiable as sponsored. This folder stores campaign content only; it does not yet publish ads or provide advertiser accounts, approvals, payments, or analytics.
