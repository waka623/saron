-- Core schema for the salon CRM / repeat-visit promotion SaaS.
-- Run via `supabase db push` or paste into the Supabase SQL editor.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- salons: one row per salon account (the "owner" is the authenticated user
-- who signs up). LINE Messaging API credentials live here so each salon can
-- connect its own LINE official account.
-- ---------------------------------------------------------------------------
create table if not exists salons (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users (id) on delete cascade,
  name text not null,
  line_channel_id text,
  line_channel_secret text,
  line_channel_access_token text,
  created_at timestamptz not null default now()
);

create index if not exists salons_owner_id_idx on salons (owner_id);

-- ---------------------------------------------------------------------------
-- staff: stylists/staff belonging to a salon.
-- ---------------------------------------------------------------------------
create table if not exists staff (
  id uuid primary key default gen_random_uuid(),
  salon_id uuid not null references salons (id) on delete cascade,
  name text not null,
  role text,
  created_at timestamptz not null default now()
);

create index if not exists staff_salon_id_idx on staff (salon_id);

-- ---------------------------------------------------------------------------
-- customers: the salon's own customer list ("karte" header). line_link_token
-- is a one-time token embedded in a QR/link so a customer's LINE account can
-- be linked to their customer record when they add the salon's official
-- account as a friend.
-- ---------------------------------------------------------------------------
create table if not exists customers (
  id uuid primary key default gen_random_uuid(),
  salon_id uuid not null references salons (id) on delete cascade,
  name text not null,
  phone text,
  line_user_id text,
  line_link_token uuid not null default gen_random_uuid(),
  birthday date,
  notes text,
  created_at timestamptz not null default now(),
  unique (salon_id, line_link_token)
);

create index if not exists customers_salon_id_idx on customers (salon_id);
create index if not exists customers_line_user_id_idx on customers (line_user_id);

-- ---------------------------------------------------------------------------
-- visit_records: the "karte" body — one row per visit/treatment.
-- salon_id is denormalized from customers so RLS policies stay a single join.
-- ---------------------------------------------------------------------------
create table if not exists visit_records (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references customers (id) on delete cascade,
  salon_id uuid not null references salons (id) on delete cascade,
  staff_id uuid references staff (id) on delete set null,
  visit_date date not null default current_date,
  menu text,
  memo text,
  photo_urls text[] not null default '{}',
  created_at timestamptz not null default now()
);

create index if not exists visit_records_customer_id_idx on visit_records (customer_id);
create index if not exists visit_records_salon_id_visit_date_idx on visit_records (salon_id, visit_date desc);

-- ---------------------------------------------------------------------------
-- campaigns: repeat-visit promotion rules (birthday / dormant-customer /
-- custom). The scheduled job matches customers against these rules and
-- sends a LINE push message.
-- ---------------------------------------------------------------------------
create table if not exists campaigns (
  id uuid primary key default gen_random_uuid(),
  salon_id uuid not null references salons (id) on delete cascade,
  name text not null,
  type text not null check (type in ('birthday', 'no_visit_reminder', 'custom')),
  days_since_last_visit int,
  message_template text not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create index if not exists campaigns_salon_id_idx on campaigns (salon_id);

-- ---------------------------------------------------------------------------
-- campaign_logs: send history, also used to avoid sending the same
-- campaign to the same customer twice within its trigger window.
-- ---------------------------------------------------------------------------
create table if not exists campaign_logs (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns (id) on delete cascade,
  customer_id uuid not null references customers (id) on delete cascade,
  sent_at timestamptz not null default now(),
  status text not null check (status in ('sent', 'failed', 'skipped')),
  error_message text
);

create index if not exists campaign_logs_campaign_id_idx on campaign_logs (campaign_id);
create index if not exists campaign_logs_customer_id_sent_at_idx on campaign_logs (customer_id, sent_at desc);

-- ---------------------------------------------------------------------------
-- Row Level Security: every table is scoped to the salon(s) owned by the
-- authenticated user. Service-role access (webhook, scheduled campaign
-- runner) bypasses RLS entirely, so these policies only govern the
-- dashboard UI.
-- ---------------------------------------------------------------------------
alter table salons enable row level security;
alter table staff enable row level security;
alter table customers enable row level security;
alter table visit_records enable row level security;
alter table campaigns enable row level security;
alter table campaign_logs enable row level security;

create policy "owners can manage their salons"
  on salons for all
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

create policy "owners can manage their staff"
  on staff for all
  using (salon_id in (select id from salons where owner_id = auth.uid()))
  with check (salon_id in (select id from salons where owner_id = auth.uid()));

create policy "owners can manage their customers"
  on customers for all
  using (salon_id in (select id from salons where owner_id = auth.uid()))
  with check (salon_id in (select id from salons where owner_id = auth.uid()));

create policy "owners can manage their visit records"
  on visit_records for all
  using (salon_id in (select id from salons where owner_id = auth.uid()))
  with check (salon_id in (select id from salons where owner_id = auth.uid()));

create policy "owners can manage their campaigns"
  on campaigns for all
  using (salon_id in (select id from salons where owner_id = auth.uid()))
  with check (salon_id in (select id from salons where owner_id = auth.uid()));

create policy "owners can view their campaign logs"
  on campaign_logs for select
  using (
    campaign_id in (
      select id from campaigns where salon_id in (
        select id from salons where owner_id = auth.uid()
      )
    )
  );
