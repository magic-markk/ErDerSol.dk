-- Suggested join between outdoor_seating_places and smiley.
--
-- The two datasets do not share a stable ID, so this view picks the best
-- Smiley match per outdoor place using postcode + address/name similarity.

create extension if not exists pg_trgm with schema extensions;

create or replace function public.normalize_match_text(input text)
returns text
language sql
immutable
as $$
  with cleaned as (
    select regexp_replace(
      lower(coalesce(input, '')),
      '[^[:alnum:]]+',
      ' ',
      'g'
    ) as value
  ),
  without_company_words as (
    select regexp_replace(
      value,
      '\m(aps|as|is|smba|v)\M',
      ' ',
      'g'
    ) as value
    from cleaned
  )
  select trim(regexp_replace(value, '\s+', ' ', 'g'))
  from without_company_words;
$$;

create or replace view public.outdoor_smiley_matches as
with outdoor_normalized as (
  select
    o.*,
    substring(o.address from ',\s*(\d{4})\s') as outdoor_postnr,
    public.normalize_match_text(o.name) as outdoor_name_norm,
    public.normalize_match_text(split_part(o.address, ',', 1)) as outdoor_street_norm
  from public.outdoor_seating_places o
),
best_matches as (
  select
    o.id as outdoor_id,
    s.navnelbnr as smiley_navnelbnr,
    s.cvrnr as smiley_cvrnr,
    s.pnr as smiley_pnr,
    s.navn as smiley_navn,
    s.adresse as smiley_adresse,
    s.postnr as smiley_postnr,
    s.bynavn as smiley_bynavn,
    s.seneste_kontrol,
    s.seneste_kontrol_dato,
    s.url as smiley_url,
    scores.name_similarity,
    scores.address_similarity,
    scores.match_score,
    case
      when scores.address_similarity >= 0.90 and scores.name_similarity >= 0.55
        then 'strong_address_and_name'
      when scores.address_similarity >= 0.92
        then 'strong_address'
      when scores.name_similarity >= 0.75
        then 'strong_name'
      when scores.match_score >= 0.65
        then 'possible_match'
      else 'weak_match'
    end as match_quality
  from outdoor_normalized o
  cross join lateral (
    select
      s.*,
      extensions.similarity(o.outdoor_name_norm, public.normalize_match_text(s.navn)) as name_similarity,
      extensions.similarity(o.outdoor_street_norm, public.normalize_match_text(s.adresse)) as address_similarity,
      (
        extensions.similarity(o.outdoor_street_norm, public.normalize_match_text(s.adresse)) * 0.65
        + extensions.similarity(o.outdoor_name_norm, public.normalize_match_text(s.navn)) * 0.35
      ) as match_score
    from public.smiley s
    where s.postnr = o.outdoor_postnr
      and (
        extensions.similarity(public.normalize_match_text(s.adresse), o.outdoor_street_norm) >= 0.30
        or extensions.similarity(public.normalize_match_text(s.navn), o.outdoor_name_norm) >= 0.30
      )
    order by
      (
        extensions.similarity(o.outdoor_street_norm, public.normalize_match_text(s.adresse)) * 0.65
        + extensions.similarity(o.outdoor_name_norm, public.normalize_match_text(s.navn)) * 0.35
      ) desc,
      extensions.similarity(o.outdoor_street_norm, public.normalize_match_text(s.adresse)) desc,
      s.seneste_kontrol_dato desc nulls last
    limit 1
  ) scores
  join public.smiley s on s.navnelbnr = scores.navnelbnr
)
select
  o.id as outdoor_id,
  o.name as outdoor_name,
  o.address as outdoor_address,
  o.lat,
  o.lon,
  o.category,
  o.outdoor_seating,
  o.outdoor_seating_source,
  o.google_place_id,
  o.google_rating,
  o.google_user_rating_count,
  o.google_maps_uri,
  b.smiley_navnelbnr,
  b.smiley_cvrnr,
  b.smiley_pnr,
  b.smiley_navn,
  b.smiley_adresse,
  b.smiley_postnr,
  b.smiley_bynavn,
  b.seneste_kontrol,
  b.seneste_kontrol_dato,
  b.smiley_url,
  b.name_similarity,
  b.address_similarity,
  b.match_score,
  b.match_quality
from outdoor_normalized o
left join best_matches b on b.outdoor_id = o.id;

comment on view public.outdoor_smiley_matches is
  'Best-effort match between outdoor seating places and Smiley records.';
