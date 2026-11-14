-- Vaani · Supabase schema
-- Run once in Supabase → SQL Editor → New query → paste → Run.
--
-- Security model:
--   * n8n writes with the SERVICE ROLE key (bypasses RLS).
--   * The public dashboard reads with the ANON key, only through the *_public views,
--     which mask phone numbers. Raw tables are not readable by anon.

create extension if not exists pgcrypto;

-- 1. Campaigns: one business + one goal (Divyasree WOW is campaign #1)
create table if not exists campaigns (
  id              text primary key,                 -- e.g. 'divyasree-wow'
  name            text not null,
  client          text not null,
  agent_name      text not null default 'Aanya',
  goal            text,
  vapi_assistant_id text,
  facts_md        text,                              -- published fact sheet
  created_at      timestamptz not null default now()
);

-- 2. Leads: imported from any file
create table if not exists leads (
  id              uuid primary key default gen_random_uuid(),
  campaign_id     text references campaigns(id) default 'divyasree-wow',
  name            text,
  phone           text not null unique,              -- E.164, e.g. +919876543210
  email           text,
  location        text,
  budget          text,
  notes           text,
  source          text,                              -- file name it came from
  status          text not null default 'new'
                  check (status in ('new','queued','calling','called','no_answer','do_not_call')),
  interest        text check (interest in ('hot','warm','cold')),
  attempts        int  not null default 0,
  last_called_at  timestamptz,
  callback_time   text,
  extra           jsonb not null default '{}'::jsonb, -- unmapped columns are kept here
  created_at      timestamptz not null default now()
);
create index if not exists leads_status_idx on leads (status, attempts);

-- 3. Calls: one row per finished call (written by n8n WF4)
create table if not exists calls (
  id              uuid primary key default gen_random_uuid(),
  vapi_call_id    text unique not null,
  lead_id         uuid references leads(id) on delete set null,
  campaign_id     text references campaigns(id) default 'divyasree-wow',
  name            text,
  phone           text,
  call_type       text,                              -- webCall | outboundPhoneCall
  started_at      timestamptz,
  ended_at        timestamptz,
  duration_sec    numeric,
  ended_reason    text,
  cost_usd        numeric,
  recording_url   text,                              -- Vapi recording URL
  storage_path    text,                              -- copy in Supabase Storage
  transcript      text,                              -- full conversation, plain text
  ai_lines        text,                              -- only what Aanya said
  messages        jsonb,                             -- turn-by-turn
  summary         text,
  interest        text check (interest in ('hot','warm','cold')),
  intent          text,
  geography_fit   text,
  budget_fit      text,
  timeline_fit    text,
  sentiment_start text,
  sentiment_end   text,
  language        text,
  callback_time   text,
  do_not_call     boolean default false,
  analysis        jsonb,                             -- full structured output
  raw             jsonb,                             -- full Vapi end-of-call report
  created_at      timestamptz not null default now()
);
create index if not exists calls_started_idx on calls (started_at desc);

-- 4. Public read views for the dashboard (phone numbers masked)
create or replace view leads_public as
  select id, campaign_id, name,
         left(phone, 3) || ' xxxxx ' || right(phone, 3) as phone,
         location, budget, source, status, interest, attempts, last_called_at, callback_time, created_at
  from leads;

create or replace view calls_public as
  select id, vapi_call_id, lead_id, campaign_id, name, call_type, started_at, ended_at, duration_sec,
         ended_reason, recording_url, transcript, messages, summary, interest, intent, geography_fit,
         budget_fit, timeline_fit, sentiment_start, sentiment_end, language, callback_time
  from calls;

-- 5. Row Level Security: lock raw tables; expose only the views
alter table campaigns enable row level security;
alter table leads     enable row level security;
alter table calls     enable row level security;

revoke all on leads, calls from anon, authenticated;
grant select on leads_public, calls_public to anon, authenticated;
grant select on campaigns to anon, authenticated;
drop policy if exists "public read campaigns" on campaigns;
create policy "public read campaigns" on campaigns for select using (true);

-- 6. Storage bucket for call recordings (private; n8n uploads with the service key)
insert into storage.buckets (id, name, public)
values ('recordings', 'recordings', false)
on conflict (id) do nothing;

-- 7. Seed campaign #1
insert into campaigns (id, name, client, agent_name, goal)
values ('divyasree-wow', 'Whispers of the Wind', 'Divyasree Developers', 'Aanya',
        'Qualify the lead and book a follow-up call with a Property Expert')
on conflict (id) do nothing;
