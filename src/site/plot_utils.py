"""Export attendee map/network data for the static site (`js/locations.js`)."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
import pandas as pd
from src.data_paths import DELEGATES_JSON
from src.util.geo_math import haversine_km as _haversine_km
AUCKLAND_LAT = -36.8485
AUCKLAND_LON = 174.7633

def _coerce_coordinate_series(series: pd.Series) -> pd.Series:
    """Convert coordinate columns to float, dropping non-numeric values."""
    return pd.to_numeric(series, errors='coerce')

def _geocoded_points(df: pd.DataFrame, *, lat_col: str='latitude', lon_col: str='longitude') -> pd.DataFrame:
    points = df.copy()
    points[lat_col] = _coerce_coordinate_series(points[lat_col])
    points[lon_col] = _coerce_coordinate_series(points[lon_col])
    points = points.dropna(subset=[lat_col, lon_col])
    valid = points[lat_col].between(-90, 90, inclusive='both') & points[lon_col].between(-180, 180, inclusive='both')
    return points.loc[valid].copy()

def _programme_map_frame(df: pd.DataFrame, *, title_col: str='title') -> pd.DataFrame:
    """Drop attended-only placeholder rows used for emissions geocodes."""
    if df.empty:
        return df.copy()
    if 'attended_only' in df.columns:
        attended_only = df['attended_only'].fillna(False)
        if attended_only.dtype == object:
            attended_only = attended_only.map(lambda value: str(value).strip().lower() in {'true', '1', 'yes'})
        programme = df.loc[~attended_only.astype(bool)].copy()
    else:
        programme = df.copy()
    if title_col in programme.columns:
        titles = programme[title_col]
        has_title = titles.notna() & titles.astype(str).str.strip().ne('') & titles.astype(str).str.strip().str.lower().ne('nan')
        programme = programme.loc[has_title].copy()
    elif 'talk_id' in programme.columns:
        talk_ids = programme['talk_id']
        has_id = talk_ids.notna() & talk_ids.astype(str).str.strip().ne('')
        programme = programme.loc[has_id].copy()
    return programme

def _attended_only_map_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Rows for attended non-presenters (geocode coverage / delegate-only map pins)."""
    if df.empty or 'attended_only' not in df.columns:
        return df.iloc[0:0].copy()
    attended_only = df['attended_only'].fillna(False)
    if attended_only.dtype == object:
        attended_only = attended_only.map(lambda value: str(value).strip().lower() in {'true', '1', 'yes'})
    return df.loc[attended_only.astype(bool)].copy()

def _as_delegate_only_locations(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark affiliation pins that only contain non-presenting attendees."""
    output: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        details = []
        for speaker in record.get('speaker_details') or []:
            details.append({
                **speaker,
                'talk_titles': [],
                'non_speaking_delegate': True,
            })
        if not details:
            continue
        output.append({
            **record,
            'id': f'delegate-export-{index:04d}',
            'speakers': [item['name'] for item in details],
            'speaker_details': details,
            'speaker_count': len(details),
            'talk_count': 0,
            'connection_count': 0,
            'delegate_only': True,
            'non_speaking_delegate_count': len(details),
            'geocode_level': record.get('geocode_level') or 'delegate list',
        })
    return output

def _merge_attended_delegates_into_locations(
    locations: list[dict[str, Any]],
    attended_records: list[dict[str, Any]],
    *,
    talk_titles_by_person_key: dict[str, list[dict[str, Any]]],
) -> int:
    """Add attended non-presenters to an existing affiliation pin when one already exists."""
    from src.geocoding.geocode import canonical_affiliation_key

    by_key: dict[str, dict[str, Any]] = {}
    for location in locations:
        affiliation = str(location.get('affiliation') or '').strip()
        key = canonical_affiliation_key(affiliation)
        if key:
            by_key[key] = location

    merged = 0
    for record in attended_records:
        affiliation_key = canonical_affiliation_key(str(record.get('affiliation') or ''))
        location = by_key.get(affiliation_key)
        if location is None:
            continue
        existing_keys = {
            str(speaker.get('person_key') or '').strip()
            for speaker in location.get('speaker_details') or []
            if str(speaker.get('person_key') or '').strip()
        }
        for speaker in record.get('speaker_details') or []:
            person_key = str(speaker.get('person_key') or '').strip()
            if person_key and person_key in existing_keys:
                continue
            location.setdefault('speaker_details', []).append(
                {
                    **speaker,
                    'talk_titles': talk_titles_by_person_key.get(person_key, []),
                    'non_speaking_delegate': True,
                }
            )
            if person_key:
                existing_keys.add(person_key)
            merged += 1
        details = location.get('speaker_details') or []
        location['speakers'] = [str(item.get('name') or '') for item in details if str(item.get('name') or '').strip()]
        location['speaker_count'] = len(details)
    return merged

def _build_talk_title_index(df: pd.DataFrame, *, presenter_col: str='presenter', affiliation_col: str='affiliation', title_col: str='title', show_progress: bool=False) -> dict[str, list[dict[str, Any]]]:
    from src.site.export_progress import make_progress
    from src.sources.delegates import delegate_person_key
    index: dict[str, dict[str, dict[str, Any]]] = {}
    working = _slim_talk_frame(df, presenter_col=presenter_col, affiliation_col=affiliation_col, title_col=title_col, include_talk_id=True)
    rows = list(working.itertuples(index=False, name=None))
    columns = list(working.columns)
    presenter_idx = columns.index(presenter_col)
    affiliation_idx = columns.index(affiliation_col)
    title_idx = columns.index(title_col) if title_col in columns else None
    authors_idx = columns.index('authors')
    talk_id_idx = columns.index('talk_id') if 'talk_id' in columns else None
    progress = make_progress(disable=not show_progress)
    with progress:
        task_id = progress.add_task('Indexing talk titles by person', total=len(rows))
        for row in rows:
            if title_idx is None:
                progress.advance(task_id)
                continue
            title = row[title_idx]
            if pd.isna(title) or not str(title).strip():
                progress.advance(task_id)
                continue
            title_text = str(title).strip()
            presenter = row[presenter_idx]
            presenter_text = '' if pd.isna(presenter) else str(presenter).strip()
            affiliation = row[affiliation_idx]
            affiliation_text = '' if pd.isna(affiliation) else str(affiliation).strip()
            authors = _talk_authors_from_values(row[authors_idx], presenter)
            if not authors:
                progress.advance(task_id)
                continue
            presenter_key = delegate_person_key(presenter_text, affiliation=affiliation_text) if presenter_text else ''
            for author in authors:
                person_key = delegate_person_key(author, affiliation=affiliation_text)
                if not person_key:
                    from src.sources.delegates import normalize_person_name
                    person_key = normalize_person_name(author)
                    if not person_key:
                        continue
                author_bucket = index.setdefault(person_key, {})
                is_primary = person_key == presenter_key or (not presenter_key and str(author).strip().casefold() == str(authors[0]).strip().casefold())
                talk_id = row[talk_id_idx] if talk_id_idx is not None else None
                talk_id_text = '' if pd.isna(talk_id) else str(talk_id).strip()
                existing = author_bucket.get(title_text)
                if not existing or (is_primary and (not existing.get('primary'))):
                    entry = {'title': title_text, 'primary': is_primary}
                    if talk_id_text:
                        entry['talk_id'] = talk_id_text
                    author_bucket[title_text] = entry
            progress.advance(task_id)
    result: dict[str, list[dict[str, Any]]] = {}
    for person_key, titles in sorted(index.items()):
        result[person_key] = sorted(titles.values(), key=lambda item: (not item['primary'], item['title'].casefold()))
    return result

def _affiliation_location_records(df: pd.DataFrame, *, lat_col: str='latitude', lon_col: str='longitude', affiliation_col: str='affiliation', presenter_col: str='presenter', title_col: str='title', abstract_col: str='abstract', auckland_lat: float=AUCKLAND_LAT, auckland_lon: float=AUCKLAND_LON, show_progress: bool=False) -> list[dict[str, Any]]:
    """Group geocoded talks by canonical affiliation."""
    from src.registry.key_resolution import AFFILIATION_KEY_COL, get_registry_key_resolver
    from src.sources.delegates import delegate_person_key
    from src.site.export_progress import make_progress
    from src.geocoding.geocode import affiliation_display_name, canonical_affiliation_key
    from src.geocoding.affiliation_geocodes import resolve_geocode
    points = _geocoded_points(df, lat_col=lat_col, lon_col=lon_col)
    if points.empty:
        return []
    resolver = get_registry_key_resolver()
    key_to_canonical = resolver.key_to_canonical
    attended_by_key = {person_key: str(person.get('attended') or '').strip().lower() in {'true', '1', 'yes'} for person_key, person in resolver.people_by_key.items()}

    def _person_key(name: object, affiliation: object='') -> str:
        cleaned = str(name or '').strip()
        if not cleaned:
            return ''
        return delegate_person_key(cleaned, affiliation=str(affiliation or ''))

    def _display_name(name: object, affiliation: object='') -> str:
        cleaned = str(name or '').strip()
        if not cleaned:
            return ''
        return key_to_canonical.get(_person_key(cleaned, affiliation), cleaned)
    working = points.copy()
    affiliation_text = working[affiliation_col].fillna('').astype(str)
    working['_lat_r'] = working[lat_col].astype(float).round(4)
    working['_lon_r'] = working[lon_col].astype(float).round(4)
    if AFFILIATION_KEY_COL in working.columns:
        registry_aff_keys = working[AFFILIATION_KEY_COL].fillna('').astype(str).str.strip()
        working['_aff_key'] = registry_aff_keys.where(registry_aff_keys.ne(''), affiliation_text.map(canonical_affiliation_key))
    else:
        working['_aff_key'] = affiliation_text.map(canonical_affiliation_key)
    working['_bucket'] = working['_aff_key'] + '\t' + working['_lat_r'].astype(str) + '\t' + working['_lon_r'].astype(str)
    working['_display_candidate'] = affiliation_text.map(lambda value: affiliation_display_name(value) or value if value.strip() else '')
    display_name = working.groupby('_bucket', sort=False)['_display_candidate'].agg(lambda values: max(values, key=len)).to_dict()
    records: list[dict[str, Any]] = []
    bucket_groups = list(working.groupby('_bucket', sort=True))
    progress = make_progress(disable=not show_progress)
    with progress:
        task_id = progress.add_task('Grouping affiliations into map pins', total=len(bucket_groups))
        for index, (bucket_key, group) in enumerate(bucket_groups, start=1):
            lat = float(group[lat_col].iloc[0])
            lon = float(group[lon_col].iloc[0])
            display = display_name.get(bucket_key) or bucket_key.split('\t', 1)[0]
            speaker_by_key: dict[str, dict[str, Any]] = {}
            for presenter, speaker_group in group.groupby(presenter_col, dropna=True):
                if pd.isna(presenter):
                    continue
                presenter_name = str(presenter)
                sample_affiliation = str(speaker_group[affiliation_col].dropna().iloc[0] if affiliation_col in speaker_group.columns and (not speaker_group[affiliation_col].dropna().empty) else '')
                from src.registry.key_resolution import PERSON_KEY_COL
                if PERSON_KEY_COL in speaker_group.columns:
                    key_values = speaker_group[PERSON_KEY_COL].dropna().astype(str).str.strip()
                    person_key = key_values.iloc[0] if not key_values.empty else ''
                else:
                    person_key = ''
                if not person_key:
                    person_key = _person_key(presenter_name, sample_affiliation)
                titles = speaker_group[title_col].dropna().astype(str).str.strip()
                talk_titles = titles[titles != ''].tolist()
                abstract_parts = (
                    speaker_group[abstract_col].dropna().astype(str).str.strip()
                    if abstract_col in speaker_group.columns
                    else pd.Series(dtype=str)
                )
                abstract_parts = abstract_parts[abstract_parts != ''].tolist()
                search_text = ' '.join([presenter_name, *talk_titles, *abstract_parts]).lower()
                existing = speaker_by_key.get(person_key)
                if existing is None:
                    speaker_by_key[person_key] = {'name': _display_name(presenter_name, sample_affiliation), 'search_text': search_text, 'talk_titles': talk_titles, 'person_key': person_key, 'attended': attended_by_key.get(person_key, False)}
                    continue
                existing['search_text'] = f"{existing['search_text']} {search_text}".strip()
                existing['talk_titles'].extend(talk_titles)
            speaker_details = sorted(speaker_by_key.values(), key=lambda item: str(item['name']).casefold())
            speakers = [item['name'] for item in speaker_details]
            level = group.get('geocode_level')
            geocode_level = ''
            if level is not None:
                levels = [value for value in level.dropna().unique() if str(value).strip()]
                if levels:
                    geocode_level = 'institute' if 'institute' in levels else str(levels[0])
            search_parts = [display, *speakers]
            for item in speaker_details:
                search_parts.append(item['search_text'])
            sample_affiliation = next((value for value in group[affiliation_col].dropna().astype(str).unique() if str(value).strip()), display)
            override_hit = resolve_geocode(sample_affiliation)
            if override_hit and override_hit.get('latitude') is not None:
                lat = float(override_hit['latitude'])
                lon = float(override_hit['longitude'])
                if override_hit.get('geocode_level'):
                    geocode_level = str(override_hit['geocode_level'])
            affiliation_label = sample_affiliation if ',' in sample_affiliation else display
            records.append({'id': f'loc-{index:04d}', 'affiliation': affiliation_label, 'lat': lat, 'lon': lon, 'speakers': speakers, 'speaker_details': speaker_details, 'speaker_count': len(speakers), 'talk_count': len(group), 'geocode_level': geocode_level, 'distance_km': round(_haversine_km(lat, lon, auckland_lat, auckland_lon), 1), 'search_text': ' '.join(search_parts).lower()})
            progress.advance(task_id)
    return records

def _delegate_affiliation_by_person_key(delegates_path: str | Path=DELEGATES_JSON) -> dict[str, str]:
    """Map registry person_key to affiliation from the official delegate list."""
    from src.geocoding.geocode import affiliation_display_name
    from src.sources.delegates import delegate_affiliation_for_row, delegate_person_key, load_delegates
    path = Path(delegates_path)
    if not path.exists():
        return {}
    mapping: dict[str, str] = {}
    for _, row in load_delegates(json_path=path).iterrows():
        name = str(row.get('full_name') or '').strip()
        affiliation = delegate_affiliation_for_row(row)
        if not name or not affiliation:
            continue
        display = affiliation_display_name(affiliation) or affiliation
        person_key = delegate_person_key(name, affiliation=display)
        if person_key:
            mapping[person_key] = display
    return mapping

def _check_in_affiliation_by_person_key() -> dict[str, str]:
    """Map registry person_key to affiliation from Innovators check-in rows."""
    from src.registry.check_in_attendance import check_in_affiliation_by_person_key
    return check_in_affiliation_by_person_key()

def _affiliation_coord_index(locations: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    from src.geocoding.geocode import affiliation_base_name, affiliation_display_name, canonical_affiliation_key
    from src.registry.affiliation_registry import parse_affiliation_parts
    index: dict[str, tuple[float, float]] = {}
    for location in locations:
        coords = (location['lat'], location['lon'])
        affiliation = location['affiliation']
        organisation, country = parse_affiliation_parts(affiliation)
        candidates = [affiliation]
        if organisation and country:
            candidates.append(f'{organisation}, {country}')
        candidates.extend((affiliation_display_name(affiliation), affiliation_base_name(affiliation), canonical_affiliation_key(affiliation)))
        for candidate in candidates:
            if candidate and candidate not in index:
                index[candidate] = coords
    return index

def _resolve_affiliation_coords(affiliation: str, coord_index: dict[str, tuple[float, float]]) -> tuple[str, tuple[float, float] | None]:
    from src.geocoding.geocode import affiliation_base_name, affiliation_display_name, canonical_affiliation_key
    if not affiliation:
        return ('', None)
    display = affiliation_display_name(affiliation) or affiliation_base_name(affiliation) or affiliation
    for candidate in (affiliation, display, affiliation_base_name(affiliation), canonical_affiliation_key(affiliation)):
        if candidate in coord_index:
            return (display, coord_index[candidate])
    return (display, None)

def _talk_authors_from_values(authors: Any, presenter: Any) -> list[str]:
    if isinstance(authors, list) and authors:
        cleaned = [str(author).strip() for author in authors if str(author).strip()]
        if cleaned:
            return cleaned
    if pd.isna(presenter):
        return []
    cleaned_presenter = str(presenter).strip()
    return [cleaned_presenter] if cleaned_presenter else []

def _slim_talk_frame(df: pd.DataFrame, *, presenter_col: str='presenter', affiliation_col: str='affiliation', title_col: str='title', include_talk_id: bool=False) -> pd.DataFrame:
    columns = [presenter_col, affiliation_col, 'authors']
    if title_col in df.columns:
        columns.append(title_col)
    if include_talk_id and 'talk_id' in df.columns:
        columns.append('talk_id')
    return df.loc[:, [column for column in columns if column in df.columns]].copy()

def _unmapped_author_network_key(author: str) -> str:
    from src.sources.delegates import normalize_person_name
    norm = normalize_person_name(author)
    return f'unmapped:{norm}' if norm else ''

def _resolve_network_author_key(author: str, affiliation_text: str) -> tuple[str, bool]:
    """Return (network_key, is_registry_person)."""
    from src.sources.delegates import delegate_person_key
    person_key = delegate_person_key(author, affiliation=affiliation_text)
    if person_key:
        return (person_key, True)
    return (_unmapped_author_network_key(author), False)

def _truthy_export_flag(value: object) -> bool:
    return str(value or '').strip().lower() in {'true', '1', 'yes'}

def _build_network_data(df: pd.DataFrame, locations: list[dict[str, Any]], *, affiliation_col: str='affiliation', presenter_col: str='presenter', show_progress: bool=False) -> dict[str, Any]:
    """Build co-authorship networks at individual and affiliation level."""
    from src.registry.key_resolution import get_registry_key_resolver
    from src.site.export_progress import make_progress
    resolver = get_registry_key_resolver()
    key_to_canonical = resolver.key_to_canonical
    attended_by_key = {person_key: _truthy_export_flag(person.get('attended')) for person_key, person in resolver.people_by_key.items()}
    in_programme_by_key = {person_key: _truthy_export_flag(person.get('in_programme')) for person_key, person in resolver.people_by_key.items()}
    delegate_affiliations_by_key = _delegate_affiliation_by_person_key()
    check_in_affiliations_by_key = _check_in_affiliation_by_person_key()
    affiliation_coords = _affiliation_coord_index(locations)
    author_affiliations: dict[str, str] = {}
    explicit_affiliation: dict[str, bool] = {}
    author_labels: dict[str, str] = {}
    registry_author_keys: set[str] = set()
    presenter_person_keys: set[str] = set()
    individual_talk_count: dict[str, int] = {}
    affiliation_talk_count: dict[str, int] = {}
    individual_edges: dict[tuple[str, str], int] = {}
    affiliation_edges: dict[tuple[str, str], int] = {}
    working = _slim_talk_frame(df, presenter_col=presenter_col, affiliation_col=affiliation_col)
    columns = list(working.columns)
    presenter_idx = columns.index(presenter_col)
    affiliation_idx = columns.index(affiliation_col)
    authors_idx = columns.index('authors')
    rows = list(working.itertuples(index=False, name=None))
    progress = make_progress(disable=not show_progress)
    with progress:
        task_id = progress.add_task('Building co-authorship network', total=len(rows))
        for row in rows:
            affiliation = row[affiliation_idx]
            raw_affiliation = '' if pd.isna(affiliation) else str(affiliation).strip()
            affiliation_text = raw_affiliation
            author_keys: list[str] = []
            for author in _talk_authors_from_values(row[authors_idx], row[presenter_idx]):
                network_key, is_registry = _resolve_network_author_key(author, affiliation_text)
                if not network_key:
                    continue
                author_keys.append(network_key)
                author_labels.setdefault(network_key, str(author).strip())
                if is_registry:
                    registry_author_keys.add(network_key)
                individual_talk_count[network_key] = individual_talk_count.get(network_key, 0) + 1
            if not author_keys:
                progress.advance(task_id)
                continue
            presenter = row[presenter_idx]
            if not pd.isna(presenter) and affiliation_text:
                presenter_key, presenter_is_registry = _resolve_network_author_key(str(presenter).strip(), affiliation_text)
                if presenter_key and presenter_is_registry:
                    registry_author_keys.add(presenter_key)
                    presenter_person_keys.add(presenter_key)
                    author_affiliations[presenter_key] = affiliation_text
                    explicit_affiliation[presenter_key] = True
            if affiliation_text:
                affiliation_talk_count[affiliation_text] = affiliation_talk_count.get(affiliation_text, 0) + 1
            if len(author_keys) >= 2:
                talk_affiliations = {author_affiliations[person_key] for person_key in author_keys if person_key in author_affiliations}
                for index, person_a in enumerate(author_keys):
                    for person_b in author_keys[index + 1:]:
                        key = tuple(sorted((person_a, person_b)))
                        individual_edges[key] = individual_edges.get(key, 0) + 1
                affiliation_list = sorted(talk_affiliations)
                for index, affiliation_a in enumerate(affiliation_list):
                    for affiliation_b in affiliation_list[index + 1:]:
                        key = tuple(sorted((affiliation_a, affiliation_b)))
                        affiliation_edges[key] = affiliation_edges.get(key, 0) + 1
            progress.advance(task_id)
    for person_key in registry_author_keys:
        if person_key in check_in_affiliations_by_key:
            author_affiliations[person_key] = check_in_affiliations_by_key[person_key]
            explicit_affiliation[person_key] = True
        elif person_key in delegate_affiliations_by_key:
            author_affiliations[person_key] = delegate_affiliations_by_key[person_key]
            explicit_affiliation[person_key] = True
    individual_nodes = []
    network_key_to_id: dict[str, str] = {}
    for network_key, connections in sorted(individual_talk_count.items(), key=lambda item: (-item[1], item[0].casefold())):
        is_registry = network_key in registry_author_keys
        person_key = network_key if is_registry else ''
        attended = attended_by_key.get(person_key, False) if is_registry else False
        on_programme = in_programme_by_key.get(person_key, False) if is_registry else False
        external_coauthor = not attended and (not on_programme)
        is_explicit = explicit_affiliation.get(network_key, False)
        affiliation_text = author_affiliations.get(network_key, '') if is_explicit else ''
        affiliation_mapped = bool(affiliation_text) and is_explicit
        affiliation, coords = _resolve_affiliation_coords(affiliation_text, affiliation_coords)
        lat = None
        lon = None
        distance_km = None
        if coords:
            lat, lon = coords
            distance_km = round(_haversine_km(lat, lon, AUCKLAND_LAT, AUCKLAND_LON), 1)
        if is_registry:
            label = key_to_canonical.get(person_key, person_key)
            node_id = f'person:{person_key}'
        else:
            label = author_labels.get(network_key, network_key.removeprefix('unmapped:'))
            node_id = f"author:{network_key.removeprefix('unmapped:')}"
        network_key_to_id[network_key] = node_id
        individual_nodes.append({'id': node_id, 'label': label, 'person_key': person_key, 'kind': 'individual', 'affiliation': affiliation, 'author_role': 'presenter' if network_key in presenter_person_keys else 'co_author', 'affiliation_explicit': explicit_affiliation.get(network_key, False), 'affiliation_mapped': affiliation_mapped, 'attended': attended, 'on_programme': on_programme, 'external_coauthor': external_coauthor, 'connections': connections, 'lat': lat, 'lon': lon, 'distance_km': distance_km})

    def _individual_links(edges: dict[tuple[str, str], int]) -> list[dict[str, Any]]:
        return [{'source': network_key_to_id[source], 'target': network_key_to_id[target], 'weight': weight} for (source, target), weight in edges.items()]
    affiliation_nodes = []
    for affiliation, connections in sorted(affiliation_talk_count.items(), key=lambda item: (-item[1], item[0].casefold())):
        _, coords = _resolve_affiliation_coords(affiliation, affiliation_coords)
        lat = None
        lon = None
        distance_km = None
        if coords:
            lat, lon = coords
            distance_km = round(_haversine_km(lat, lon, AUCKLAND_LAT, AUCKLAND_LON), 1)
        affiliation_nodes.append({'id': f'aff:{affiliation}', 'label': affiliation, 'kind': 'affiliation', 'connections': connections, 'lat': lat, 'lon': lon, 'distance_km': distance_km})

    def _links(edges: dict[tuple[str, str], int], prefix: str) -> list[dict[str, Any]]:
        return [{'source': f'{prefix}{source}', 'target': f'{prefix}{target}', 'weight': weight} for (source, target), weight in edges.items()]
    return {'individual': {'nodes': individual_nodes, 'links': _individual_links(individual_edges)}, 'affiliation': {'nodes': affiliation_nodes, 'links': _links(affiliation_edges, 'aff:')}}

def _affiliation_connection_lookup_keys(affiliation: str) -> list[str]:
    """Match map pins to network affiliation nodes across label variants."""
    from src.geocoding.geocode import affiliation_base_name, affiliation_display_name
    from src.registry.affiliation_registry import parse_affiliation_parts
    affiliation = str(affiliation or '').strip()
    if not affiliation:
        return []
    keys: list[str] = [affiliation]
    organisation, country = parse_affiliation_parts(affiliation)
    if organisation and country:
        keys.append(f'{organisation}, {country}')
    display = affiliation_display_name(affiliation)
    if display:
        keys.append(display)
    base = affiliation_base_name(affiliation)
    if base:
        keys.append(base)
    if organisation:
        keys.append(organisation)
    deduped: list[str] = []
    for key in keys:
        if key and key not in deduped:
            deduped.append(key)
    return deduped

def _privacy_hidden_map_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Drop privacy-restricted non-programme delegates from map pins."""
    if df.empty or "privacy_hidden" not in df.columns:
        return df
    privacy_hidden = df["privacy_hidden"].fillna(False)
    if privacy_hidden.dtype == object:
        privacy_hidden = privacy_hidden.map(
            lambda value: str(value).strip().lower() in {"true", "1", "yes"}
        )
    return df.loc[~privacy_hidden.astype(bool)].copy()


def _attendee_site_stats(df: pd.DataFrame, locations: list[dict[str, Any]], *, presenter_col: str='presenter') -> dict[str, int]:
    mapped_speakers = sum((location['speaker_count'] for location in locations))
    total_presenters = df[presenter_col].nunique(dropna=True)
    mapped_talks = len(_geocoded_points(df))
    return {'location_count': len(locations), 'mapped_speakers': mapped_speakers, 'missing_speakers': total_presenters - mapped_speakers, 'mapped_talks': mapped_talks, 'missing_talks': len(df) - mapped_talks, 'total_speakers': total_presenters, 'total_talks': len(df)}

def export_attendee_site_data(df: pd.DataFrame, *, lat_col: str='latitude', lon_col: str='longitude', affiliation_col: str='affiliation', presenter_col: str='presenter', title_col: str='title', abstract_col: str='abstract', title: str='ICRS 2026', save_path: str | Path='js/locations.js', auckland_lat: float=AUCKLAND_LAT, auckland_lon: float=AUCKLAND_LON, show_progress: bool=False) -> Path:
    """Export grouped affiliation locations for the static JS map site."""
    from datetime import UTC, datetime
    from src.site.export_progress import console, run_with_progress
    from src.site.map_exclusions import export_map_exclusions_js, load_map_exclusions, map_talks_for_export
    map_exclusions = load_map_exclusions()
    export_map_exclusions_js()
    programme_df = _programme_map_frame(df, title_col=title_col)
    if show_progress:
        console().print('  Filtering talks for map export')
    map_df = map_talks_for_export(programme_df, exclusions=map_exclusions, presenter_col=presenter_col)
    locations = _affiliation_location_records(map_df, lat_col=lat_col, lon_col=lon_col, affiliation_col=affiliation_col, presenter_col=presenter_col, title_col=title_col, abstract_col=abstract_col, auckland_lat=auckland_lat, auckland_lon=auckland_lon, show_progress=show_progress)
    if not locations:
        raise ValueError('No geocoded affiliations available for site export.')
    if show_progress:
        console().print(f'  {len(locations):,} location pins')
    # Network is programme co-authorship only: attended non-presenters appear only if listed as authors.
    network = _build_network_data(programme_df, locations, affiliation_col=affiliation_col, presenter_col=presenter_col, show_progress=show_progress)
    talk_titles_by_person_key = _build_talk_title_index(programme_df, presenter_col=presenter_col, affiliation_col=affiliation_col, title_col=title_col, show_progress=show_progress)
    if show_progress:
        console().print('  Attaching talk titles to map speakers')
    for location in locations:
        for speaker in location['speaker_details']:
            person_key = str(speaker.get('person_key') or '').strip()
            speaker['talk_titles'] = talk_titles_by_person_key.get(person_key, [])
    affiliation_connections: dict[str, int] = {}
    for node in network['affiliation']['nodes']:
        label = str(node.get('label') or '').strip()
        if not label:
            continue
        connections = int(node.get('connections') or 0)
        for key in _affiliation_connection_lookup_keys(label):
            affiliation_connections[key] = connections
    for location in locations:
        connection_count = 0
        for key in _affiliation_connection_lookup_keys(str(location.get('affiliation') or '')):
            connection_count = affiliation_connections.get(key, 0)
            if connection_count:
                break
        location['connection_count'] = connection_count

    non_speaker_locations: list[dict[str, Any]] = []
    attended_only_df = _privacy_hidden_map_frame(_attended_only_map_frame(df))
    if not attended_only_df.empty:
        if show_progress:
            console().print('  Building delegate-only map pins for non-presenters')
        attended_only_map = map_talks_for_export(
            attended_only_df,
            exclusions=map_exclusions,
            presenter_col=presenter_col,
        )
        attended_only_records = _affiliation_location_records(
            attended_only_map,
            lat_col=lat_col,
            lon_col=lon_col,
            affiliation_col=affiliation_col,
            presenter_col=presenter_col,
            title_col=title_col,
            abstract_col=abstract_col,
            auckland_lat=auckland_lat,
            auckland_lon=auckland_lon,
            show_progress=show_progress,
        )
        from src.geocoding.geocode import canonical_affiliation_key

        speaker_keys = {
            canonical_affiliation_key(str(location.get('affiliation') or ''))
            for location in locations
            if str(location.get('affiliation') or '').strip()
        }
        merged_attended = _merge_attended_delegates_into_locations(
            locations,
            attended_only_records,
            talk_titles_by_person_key=talk_titles_by_person_key,
        )
        if show_progress and merged_attended:
            console().print(f'  Merged {merged_attended:,} attended delegate(s) into speaker pins')
        for record in _as_delegate_only_locations(attended_only_records):
            aff_key = canonical_affiliation_key(str(record.get('affiliation') or ''))
            if aff_key and aff_key in speaker_keys:
                continue
            non_speaker_locations.append(record)
        if show_progress:
            console().print(f'  {len(non_speaker_locations):,} delegate-only pins')

    stats = _attendee_site_stats(map_df, locations, presenter_col=presenter_col)
    stats['non_speaker_location_count'] = len(non_speaker_locations)
    stats['country_count'] = len({
        str(location.get('affiliation') or '').rsplit(',', 1)[-1].strip().casefold()
        for location in [*locations, *non_speaker_locations]
        if ',' in str(location.get('affiliation') or '')
    })
    payload = {
        'meta': {
            'title': title,
            'generated_at': datetime.now(UTC).isoformat(timespec='seconds'),
            'central_lon': auckland_lon,
            'auckland': {'label': 'Auckland, New Zealand', 'lat': auckland_lat, 'lon': auckland_lon},
            'stats': stats,
        },
        'locations': locations,
        'non_speaker_locations': non_speaker_locations,
        'network': network,
        'talk_titles_by_person_key': talk_titles_by_person_key,
    }
    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _serialise_and_write() -> None:
        js_body = f'/** Generated by export_attendee_site_data – do not edit by hand. */\nexport const SITE_DATA = {json.dumps(payload, ensure_ascii=False, indent=2)};\n'
        output_path.write_text(js_body, encoding='utf-8')
    if show_progress:
        run_with_progress('Serialising and writing locations.js', _serialise_and_write)
    else:
        _serialise_and_write()
    return output_path
