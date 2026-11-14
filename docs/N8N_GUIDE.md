# n8n guide: learn it by running Vaani's automations

## What is n8n? (one minute)
n8n is a visual automation tool. You connect boxes called **nodes** with arrows, and data flows from left to right.

- **Trigger node:** starts the workflow. It can be a webhook (a URL something calls), a schedule (every 5 minutes), and so on.
- **Action nodes:** do the work, such as calling an API (HTTP Request), running JavaScript (Code), or branching (IF).
- **Items:** the data passed between nodes. Each item is a JSON object. If a node outputs 3 items, the next node runs 3 times.
- **Expressions:** anything inside `{{ }}` is live JavaScript. For example:
  - `{{ $json.phone }}` is the `phone` field of the current item.
  - `{{ $('Build call row').first().json.row }}` reads another node's output.
  - `{{ $env.SUPABASE_URL }}` reads a key from your `.env`.

## Our 4 workflows

| Workflow | Trigger | What it does |
|---|---|---|
| **WF4 · End-of-call save** | Webhook `/vapi-events` (Vapi calls it when a call ends) | Saves the transcript, summary, score and recording to Supabase, updates the lead, and sends a Telegram alert for hot leads |
| **WF2 · Lead import** | Webhooks `/lead-map` and `/lead-import` (the dashboard calls them) | Groq AI works out the columns of any file; leads are cleaned, de-duplicated and saved |
| **WF3 · Auto-dialer** | Schedule, every 5 min | 10 AM–7 PM IST: picks new or no-answer leads and asks Vapi to call them (needs Twilio) |
| **WF1 · Knowledge builder** | Webhook `/knowledge-build` | Turns any business document into a clean fact sheet, so Vaani can be reused for another client |

### Example: WF4 for one call
```
Rahul hangs up
→ Vapi POSTs the report to /webhook/vapi-events            [Webhook]
→ "Is end-of-call report?" yes                              [IF]
→ wait 8 s so Vapi finishes the AI analysis                 [Wait]
→ GET the full call from Vapi (includes the hot/warm/cold)  [HTTP Request]
→ build one tidy row: summary, 4 checkpoints, mood…         [Code]
→ save it in the Supabase `calls` table                     [HTTP Request]
   ├→ update Rahul's lead: status "called", interest "hot"
   ├→ copy the recording into Supabase Storage
   └→ hot? send "🔥 Hot lead: Rahul…" on Telegram
```

## Setup (about 10 minutes)

n8n runs in **Docker** (`docker-compose.yml`). Open Docker Desktop first.

1. **Fill in `.env`** (copy `.env.example`). n8n needs `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `VAPI_PRIVATE_KEY` and `GROQ_API_KEY`.
2. **Start n8n** (`docker compose up -d`), then open http://localhost:5678 and create your local owner account:
   ```bash
   npm run n8n
   ```
3. **Import the workflows** (first time only, while n8n is running):
   ```bash
   npm run n8n:import
   ```
   Then switch each workflow to **Active / Published** in the editor.
   > **Changed `.env` later?** Run `docker compose up -d --force-recreate` so n8n picks up the new keys.

   **No Docker?** `npm run n8n:no-docker` runs the same thing with npx.
4. **Expose n8n to the internet**, so Vapi and the dashboard can reach it. In a second terminal:
   ```bash
   ngrok http 5678
   ```
   Copy the `https://….ngrok-free.app` URL into `.env`:
   - `N8N_PUBLIC_URL=https://….ngrok-free.app`
   - `N8N_VAPI_WEBHOOK_URL=https://….ngrok-free.app/webhook/vapi-events`

   Then run `docker compose up -d --force-recreate`.
5. **Activate the workflows:** open each one and switch **Active** on (WF3 only after Twilio is connected).
6. **Point Vapi at n8n:**
   ```bash
   npm run sync
   ```
   This writes the webhook URL into the assistant.
7. **Point the dashboard at n8n:** in `web/js/config.js`, set `n8nBaseUrl: 'https://….ngrok-free.app/webhook'`.

> **Note:** the free ngrok URL changes every time you restart ngrok. When it changes, repeat steps 4, 6 and 7.

## How to test without a real call
1. Open **WF4**, click **Execute workflow**, then make a call on the "Talk to Aanya" page. n8n shows the data inside every node, green for success.
2. **Pin data:** after one real run, click a node's output and **Pin** it. You can now re-run later nodes without making another call, which is great for learning and debugging.
3. **Test lead import from a terminal:**
   ```bash
   curl -X POST http://localhost:5678/webhook/lead-import -H "Content-Type: application/json" -d "{\"leads\":[{\"name\":\"Test User\",\"phone\":\"9876543210\",\"location\":\"Hebbal\"}]}"
   ```
   It answers with something like `{"imported":1,"received":1,"skipped":0}`.

## Editing the workflows
The JSON files are generated from `n8n/build_workflows.js`, which is readable JavaScript with comments. You can either:
- edit visually in n8n and **export** (⋯ → Download), or
- edit the script and run `npm run n8n:build` + `npm run n8n:import`.

## Common problems
| Symptom | Fix |
|---|---|
| `access to env vars denied` | Start n8n with `npm run n8n` (docker-compose sets `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`). |
| New keys in `.env` aren't picked up | `docker compose up -d --force-recreate` |
| `npm run n8n` fails: cannot connect to Docker | Open Docker Desktop and wait until it says "Engine running". |
| Nothing arrives after a call | Is WF4 **Active**? Is `N8N_VAPI_WEBHOOK_URL` the current ngrok URL? Run `npm run sync` again. |
| Dashboard import fails with a CORS or HTML error | Use the ngrok URL + `/webhook` in `config.js`, and make sure WF2 is active. |
| `Save call` fails with 401/404 | Check `SUPABASE_URL` / the service key, and that `supabase/schema.sql` was run. |
| Interest is empty | Vapi's AI analysis was slow. Increase the Wait node from 8 s to 15 s. |
