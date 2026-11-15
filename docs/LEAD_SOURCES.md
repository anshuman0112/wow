# Lead sources: connect once, then every lead is called automatically

Every source below sends new leads to the app. Each lead is saved **without duplicates** (same phone = same
person), tagged with its source, and **Divya calls it within seconds** (Settings → New leads; only inside
calling hours, otherwise at the start of the next window). All of these are **free**.

| Source | Address to paste | Secret |
|---|---|---|
| Website form (ready-made) | `https://vaani-divyasree.vercel.app/enquire.html` | none |
| Any form / tool (JSON) | `https://vaani-divyasree.vercel.app/api/leads/inbound` | none (rate-limited) |
| Facebook + Instagram lead ads | `https://vaani-divyasree.vercel.app/api/leads/meta` | `META_VERIFY_TOKEN`, `META_APP_SECRET`, `META_PAGE_TOKEN` |
| Google Ads lead forms | `https://vaani-divyasree.vercel.app/api/leads/google` | `GOOGLE_ADS_KEY` |

Secrets live in `.env` (local) and in Vercel's environment variables, never in code.
Test each one from **Integrations → Lead sources → Send test lead** (admin PIN).

---

## 1. Website form
Use the ready page `https://vaani-divyasree.vercel.app/enquire.html` as your ad landing page or link it from
your website. To use your own form instead, send a POST with JSON:

```js
fetch("https://vaani-divyasree.vercel.app/api/leads/inbound", {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ name, phone, location, budget, source: "Website form" })
});
```
The answer says what happened, e.g. `{"call": "calling now"}` or `{"call": "scheduled for 16 Nov, 9:00 AM"}`.

## 2. Facebook + Instagram lead ads (one connection for both)
Instagram lead ads run through Meta Ads Manager, so the same setup covers both. The app tags each lead
as **Facebook** or **Instagram** automatically.

1. You need a **Facebook Page** (free). For Instagram, link your Instagram **business** account to that Page.
2. Go to **developers.facebook.com → My Apps → Create app** (type: Business). It is free.
3. In the app: **Add product → Webhooks → Page → Subscribe to `leadgen`**.
   - Callback URL: `https://vaani-divyasree.vercel.app/api/leads/meta`
   - Verify token: the value of `META_VERIFY_TOKEN` from `.env`
   Meta checks it immediately; the app answers automatically.
4. **App settings → Basic → App secret** → put it in `META_APP_SECRET` (`.env` and Vercel).
5. Get a **Page access token** with the `leads_retrieval` and `pages_manage_metadata` permissions
   (Graph API Explorer → select your Page → generate a long-lived token) → put it in `META_PAGE_TOKEN`.
6. Subscribe the Page to the app (Graph API Explorer: `POST /{page-id}/subscribed_apps?subscribed_fields=leadgen`).
7. Test for free, without running ads: **Meta Lead Ads Testing Tool**
   (developers.facebook.com/tools/lead-ads-testing) → pick your Page and form → **Create lead**.
   The lead appears in the app within seconds.

For your own Page this works without Meta's app review. Using it for other businesses' Pages needs app review.

## 3. Google Ads lead forms
1. In Google Ads, open your **lead form asset → Lead delivery → Webhook integration**.
2. Webhook URL: `https://vaani-divyasree.vercel.app/api/leads/google`
3. Key: the value of `GOOGLE_ADS_KEY` from `.env`.
4. Press **Send test data**: a test lead appears in the app as **Google Ads (test)**.

## 4. Google Forms (free script, 2 minutes)
1. Open your Google Form → **⋮ → Script editor**, paste this, and save:

```js
function onFormSubmit(e) {
  const a = {};
  e.response.getItemResponses().forEach(r => a[r.getItem().getTitle().toLowerCase()] = r.getResponse());
  UrlFetchApp.fetch("https://vaani-divyasree.vercel.app/api/leads/inbound", {
    method: "post", contentType: "application/json", muteHttpExceptions: true,
    payload: JSON.stringify({ name: a["name"] || "", phone: a["phone"] || a["mobile"] || "",
                              location: a["city"] || "", budget: a["budget"] || "", source: "Google Forms" })
  });
}
```
2. **Triggers (clock icon) → Add trigger → onFormSubmit → From form → On form submit**.
   Name your questions "Name", "Phone", "City", "Budget".

Typeform, Tally, Jotform and similar tools: add a webhook to `/api/leads/inbound` with the same JSON fields.

---

### Free Twilio trial note
Leads with any number are saved. Only numbers verified on the Twilio trial can actually be called; other
leads show the honest reason in their note instead of a fake call.
