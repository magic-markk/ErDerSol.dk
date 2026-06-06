-- Supabase/Postgres schema for Smiley.xml.
-- XML fields are normalized to snake_case column names.

create table if not exists public.smiley (
  navnelbnr bigint primary key,
  cvrnr bigint,
  pnr bigint,
  region text,
  branche_kode text,
  branche text,
  virksomhedstype text,
  navn text not null,
  adresse text,
  postnr text,
  bynavn text,
  seneste_kontrol smallint,
  seneste_kontrol_dato date,
  naestseneste_kontrol smallint,
  naestseneste_kontrol_dato date,
  tredjeseneste_kontrol smallint,
  tredjeseneste_kontrol_dato date,
  fjerdeseneste_kontrol smallint,
  fjerdeseneste_kontrol_dato date,
  url text,
  reklame_beskyttelse boolean,
  elite_smiley boolean,
  kaedenavn text,
  geo_lng numeric(9,6),
  geo_lat numeric(8,6),
  pixibranche text,
  imported_at timestamptz not null default now(),

  constraint smiley_geo_lng_range check (geo_lng is null or geo_lng between -180 and 180),
  constraint smiley_geo_lat_range check (geo_lat is null or geo_lat between -90 and 90)
);

create index if not exists smiley_cvrnr_idx on public.smiley (cvrnr);
create index if not exists smiley_pnr_idx on public.smiley (pnr);
create index if not exists smiley_postnr_idx on public.smiley (postnr);
create index if not exists smiley_bynavn_idx on public.smiley (bynavn);
create index if not exists smiley_branche_kode_idx on public.smiley (branche_kode);
create index if not exists smiley_seneste_kontrol_idx on public.smiley (seneste_kontrol);
create index if not exists smiley_geo_idx
  on public.smiley (geo_lat, geo_lng)
  where geo_lat is not null and geo_lng is not null;

comment on table public.smiley is 'Data imported from Smiley.xml.';
comment on column public.smiley.navnelbnr is 'XML: navnelbnr';
comment on column public.smiley.branche_kode is 'XML: brancheKode';
comment on column public.smiley.navn is 'XML: navn1';
comment on column public.smiley.adresse is 'XML: adresse1';
comment on column public.smiley.bynavn is 'XML: By';
comment on column public.smiley.url is 'XML: URL';
comment on column public.smiley.elite_smiley is 'XML: Elite_Smiley';
comment on column public.smiley.kaedenavn is 'XML: Kaedenavn';
comment on column public.smiley.geo_lng is 'XML: Geo_Lng';
comment on column public.smiley.geo_lat is 'XML: Geo_Lat';
comment on column public.smiley.pixibranche is 'XML: Pixibranche';

-- Public read access for a frontend using the Supabase anon key.
-- Remove these lines if the table should only be readable server-side.
alter table public.smiley enable row level security;

drop policy if exists "Public smiley read access" on public.smiley;
create policy "Public smiley read access"
  on public.smiley
  for select
  using (true);
