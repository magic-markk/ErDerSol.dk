-- Change bar_shadow_cache from historical buckets to one latest row per venue.
-- Run this after create_bar_shadow_cache_table.sql.

delete from public.bar_shadow_cache old
using public.bar_shadow_cache newer
where old.outdoor_seating_place_id = newer.outdoor_seating_place_id
  and (
    old.calculated_for < newer.calculated_for
    or (
      old.calculated_for = newer.calculated_for
      and old.id < newer.id
    )
  );

alter table public.bar_shadow_cache
  drop constraint if exists bar_shadow_cache_unique_bucket;

alter table public.bar_shadow_cache
  add constraint bar_shadow_cache_unique_place
  unique (outdoor_seating_place_id);

drop index if exists bar_shadow_cache_place_time_idx;

create index if not exists bar_shadow_cache_calculated_for_place_idx
  on public.bar_shadow_cache (calculated_for desc, outdoor_seating_place_id);

comment on table public.bar_shadow_cache is
  'Latest cached shadow result per outdoor seating place.';
