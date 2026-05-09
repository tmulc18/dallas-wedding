-- Wedding RSVP schema for nov21.party
-- Run once via the Supabase SQL editor. Safe to re-run: tables use IF NOT EXISTS,
-- functions use CREATE OR REPLACE.

-- Tables -------------------------------------------------------------
create table if not exists guest_list (
  phone        text primary key,           -- E.164, e.g. +12145550123
  guests       text[]      not null default '{}',
  num_allowed  int         not null check (num_allowed > 0),
  created_at   timestamptz not null default now()
);

create table if not exists rsvps (
  id          uuid primary key default gen_random_uuid(),
  phone       text        not null references guest_list(phone) on delete cascade,
  guest_name  text        not null,
  attending   boolean     not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (phone, guest_name)
);

-- RLS: deny everything by default. Only the security-definer RPCs touch data.
alter table guest_list enable row level security;
alter table rsvps      enable row level security;

-- RPC: lookup --------------------------------------------------------
create or replace function lookup_guest(p_phone text)
returns table(phone text, guests text[], num_allowed int)
language sql
security definer
set search_path = public
as $$
  select phone, guests, num_allowed
  from guest_list
  where phone = p_phone;
$$;

revoke all on function lookup_guest(text) from public;
grant  execute on function lookup_guest(text) to anon, authenticated;

-- RPC: submit --------------------------------------------------------
-- p_responses: jsonb array of {name: text, attending: bool}
-- Replaces all prior responses for this phone atomically.
create or replace function submit_rsvp(p_phone text, p_responses jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_allowed int;
  r         jsonb;
  v_name    text;
begin
  select num_allowed into v_allowed
    from guest_list
   where phone = p_phone;

  if not found then
    raise exception 'unknown phone';
  end if;

  if jsonb_typeof(p_responses) <> 'array' then
    raise exception 'p_responses must be a JSON array';
  end if;

  if jsonb_array_length(p_responses) = 0 then
    raise exception 'no responses provided';
  end if;

  if jsonb_array_length(p_responses) > v_allowed then
    raise exception 'too many responses (max %)', v_allowed;
  end if;

  delete from rsvps where phone = p_phone;

  for r in select * from jsonb_array_elements(p_responses) loop
    v_name := trim(r->>'name');
    if v_name is null or v_name = '' then
      raise exception 'each response needs a non-empty name';
    end if;
    insert into rsvps(phone, guest_name, attending)
    values (p_phone, v_name, (r->>'attending')::boolean)
    on conflict (phone, guest_name) do update
      set attending  = excluded.attending,
          updated_at = now();
  end loop;
end;
$$;

revoke all on function submit_rsvp(text, jsonb) from public;
grant  execute on function submit_rsvp(text, jsonb) to anon, authenticated;
