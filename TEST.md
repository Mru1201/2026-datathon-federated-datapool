# Testing

Five layers, fastest first. Every assertion carries a message that says **what was
checked, what was expected, what was found, and where** (dataset / tool / model /
case), so a red test tells you where to look without a debugger.

| Layer | Folder | Needs | Runs in CI |
|---|---|---|---|
| 1. Unit (incl. SPARQL parity) | `tests/unit/` | nothing (offline, rdflib) | every push/PR (hosted runner) |
| 2. MCP protocol + end-to-end | `tests/protocol/` | nothing (offline: tools read `data/directory.ttl`) | every push/PR (hosted runner) |
| 3. SPARQL API | `tests/api/` | live SPARQL endpoint (skipped if unreachable) | **manual** (hosted runner) |
| 4. Connection smoke | `tests/llm/` | Open WebUI + API key | manual (self-hosted runner) |
| 5. Tool-calling evals | `tests/evals/` | Open WebUI + API key (`test_cases.py`: nothing) | manual (self-hosted runner); `test_cases.py` on every push/PR |

## Running

```bash
conda activate awo-mcp                        # or your virtualenv (see README.md)
pip install -r requirements.txt -r requirements-dev.txt   # once

pytest -m "not llm and not api"               # layers 1+2, offline, ~8 s, 0 requests (what CI runs on push)
pytest -m "not llm"                           # layers 1-3, ~1 min, ~47 requests to the SPARQL endpoint
pytest tests/unit/test_sparql_parity.py       # new queries vs. old CSV logic, offline
pytest -m api tests                           # layer 3 only: every tool against the live endpoint
pytest -m llm tests/llm                       # is Open WebUI/Ollama reachable?
pytest -m llm tests/evals                     # default model (OPENWEBUI_MODEL or first listed)
pytest -m llm tests/evals --models qwen3:8b,gemma4:12b --runs 3 --pass-threshold 0.67
pytest -m llm tests/evals --models all        # every model Open WebUI lists
pytest -k count-berlin -m llm tests/evals     # a single eval case
```

Config lives in `.env` (see `.env.example`): `OPENWEBUI_URL`, `OPENWEBUI_API_KEY`,
optional `OPENWEBUI_MODEL`, `EVAL_MODELS`, `EVAL_RUNS`, `EVAL_PASS_THRESHOLD`,
`SPARQL_ENDPOINT` (default `https://sosuse.correlaid.org/directory/sparql`).
Eval runs write `reports/eval-report.md` and `.json` (and the GitHub job summary).

## Live dashboard

`pytest` opens a dashboard in your browser (`http://127.0.0.1:8765`) and fills it as tests run:

* every test listed by layer and file, with status (pending / running / passed / failed / skipped / expected fail), duration and a progress bar
* **Expected** – the description from the tables in this file (for evals: prompt, tool, arguments and answer text from `cases.json`)
* **Actual** – every assertion with the values pytest evaluated (for `==` checks: *Actual* is the left side, *Expected* the right side – keep that order when writing tests), per-run tool calls and answers for evals, and the failure message plus traceback for failures (failed tests open automatically)
* when the run ends a standalone copy is saved to `reports/dashboard.html`

The expected text is read from the `| \`test_name\` | description |` rows in this file, so keep those rows up to date when you add tests.

```bash
pytest                          # dashboard opens automatically
pytest --dashboard-no-open      # start it but don't open a browser tab
pytest --dashboard-hold         # keep the page served after the run (Ctrl+C to quit)
pytest --dashboard-port 9000    # different port (default 8765, or $DASHBOARD_PORT)
pytest --no-dashboard           # off (also off automatically when $CI is set)
```

## Layer 1 – Unit tests (`tests/unit/`)

All MCP tools now read the live SPARQL API (`src/sparql_client.py`, see `QUERIES.md`).
The old CSV implementation (`DataLoader` + `DataRepository` in `src/legacy/`) is no longer used by
`server.py`. It stays as the **reference implementation**: `test_sparql_parity.py` checks
that every new query does exactly what the old CSV code did, and `test_loader.py` /
`test_repository.py` keep that reference correct.

Expected values are computed from the raw CSVs with the `csv` module, independent of
the code under test. Edge cases use tiny synthetic datasets (`tests/helpers.py:make_repo`).

### `test_loader.py` – `DataLoader`
| Test | Checks |
|---|---|
| `test_load_all_returns_four_datasets` | keys are exactly einrichtung, adresse, angebot, traeger |
| `test_row_count_matches_csv` (×4) | loaded rows == rows in the CSV file (nothing lost/added) |
| `test_required_columns_present` (×4) | columns that `src/legacy/data_repository.py` reads exist |
| `test_iri_is_unique_and_filled` (×4) | `iri` never empty, never duplicated |
| `test_umlauts_survive_loading` | "Lübecker" is intact (encoding) |
| `test_missing_directory_raises_clear_error` | missing data dir → `FileNotFoundError` naming the CSV |
| `test_facility_address_references_resolve` | every facility address IRI exists in `adresse` |
| `test_facility_provider_references_resolve` | every facility provider IRI exists in `traeger` |

### `test_sparql_parity.py` – new SPARQL queries vs. old CSV logic

Offline, no network. **Source: `data/directory.ttl`** (the RDF export of the directory, same
vocabulary as the live endpoint), loaded into an in-memory rdflib graph
(`tests/helpers.py:load_graph`). Both implementations get exactly the same data:

* **new:** the real `.rq` files run on the graph through `SparqlClient` with an in-memory
  rdflib backend instead of HTTP (`LocalSparqlClient`)
* **old:** `DataRepository` runs on tables derived from the graph
  (`tests/helpers.py:graph_to_frames`): one row per entity, one column per column of the
  `*Schema.csv` headers, NaN when a property is absent

The old result is the expected value. Lists are compared sorted by IRI (the SPARQL queries
return IRI order). Coordinates are compared as floats. Edge cases use small Turtle
snippets. The CSVs in `data/` are not used here: they are an older, lossy export of the
same data (e.g. phone numbers lost their leading 0), and two facilities differ.

| Test | Checks |
|---|---|
| `test_rows_flattens_bindings_and_maps_empty_to_none` | SPARQL JSON bindings → flat dicts; unbound or empty `GROUP_CONCAT` → `None` |
| `test_expand_and_column_variable` | `schema:postalCode` → full IRI and query variable `postal_code` |
| `test_to_float` | coordinate literals → float; `None` stays `None` |
| `test_dataset_columns_match_csv_headers` (×4) | `DATASETS` column lists in `sparql_client.py` == headers of the `data/*Schema.csv` files |
| `test_duplicate_query_selects_every_column` (×4) | each `list_duplicate_*.rq` compares every non-IRI column |
| `test_count_facilities_parity` (×4) | Berlin/berlin/BERLIN/Atlantis: SPARQL count == CSV count |
| `test_search_facilities_parity` (×4) | same cities: identical result rows (all 8 fields) |
| `test_get_facility_details_parity` (×7) | Drehscheibe, drehscheibe, Lübecker, (HLS6), .*, AWO, empty: identical details incl. nested address and provider |
| `test_search_services_parity` (×7) | Suchtberatung, sucht, Senioren, Pflege, Beratung, no-match, empty: identical services |
| `test_detect_duplicates_parity` | same groups as the pandas duplicate logic with the IRI column left out |
| `test_check_completeness_parity` | identical rows/columns/missing counts and percentages for all 4 datasets |
| `test_generate_statistics_parity` (×7) | each statistics section identical (sizes, by city/category/provider, relationships, services by category/audience) |
| `test_compare_facilities_parity` | identical result for Drehscheibe vs. Metropolitankapitel |
| `test_casefold_matches_eszett_like_python` | Gießen / GIESSEN / giessen all match, like Python `casefold()` |
| `test_dangling_address_is_skipped_like_csv` | an address link to a missing address counts as "no address" in count, search, details and statistics |
| `test_whitespace_values_count_as_missing_and_are_trimmed` | whitespace-only values are missing in completeness; statistics trim values (" Pflege " = "Pflege") |
| `test_injected_duplicate_is_found` | two facilities with identical values (different IRIs) → one group, `occurrences == 2`, both IRIs |
| `test_quote_in_input_stays_inside_the_literal` | quotes in names/queries are matched literally; `") or true or ("` returns nothing |
| `test_empty_city_matches_nothing` | a facility without an address matches no city: `count_facilities("")` is 0 and `search_facilities("")` is empty, in both implementations |
| `test_multi_valued_contacts_are_joined` | RDF allows several emails per facility (a CSV cell cannot): all are returned, joined with "; "; `graph_to_frames` refuses such data |
| `test_escape_literal_used_for_every_placeholder` | placeholder values are escaped in every query |

### `test_fix_first.py` / `test_fix_first_sparql.py` – `records_to_fix_first`

`test_fix_first.py` checks the ranking logic in `src/fix_first.py` (buckets, scoring, tiers,
filters, provider batches, urgent focus) on a small fake repository, so it does not depend
on the data source. `test_fix_first_sparql.py` runs the real
`list_facility_quality_fields_by_city.rq` on `data/directory.ttl`:

| Test | Checks |
|---|---|
| `test_repository_has_one_row_per_facility_in_city` | one row per Berlin facility, as many as `count_facilities("Berlin")` |
| `test_repository_addresses_belong_to_the_city` | every address in the repository is in Berlin |
| `test_ranking_runs_and_counts_match` | summary total == `count_facilities`; at most `n` results, each with a priority tier |
| `test_unknown_city_gives_empty_result` | unknown city → 0 facilities, no results |

### `test_query_files.py` – query files and query building

| Test | Checks |
|---|---|
| `test_escape_literal_escapes_quotes_and_backslashes` | quotes, backslashes and newlines are escaped for a SPARQL string literal |
| `test_load_query_embeds_escaped_city` | `load_query` fills `{{city}}` in `count_facilities_by_city.rq` with the escaped value |
| `test_load_query_without_required_param_raises` | a missing placeholder value raises `ValueError` naming the parameter |
| `test_query_files_follow_naming_convention` (×1 per `.rq` file) | name matches `<action>_<entity>[_by_<param>][_per_<group>].rq`; every `{{param}}` is named after `_by_`; `_per_` queries use `GROUP BY`; `# Params:` and `# Used by:` header present |

### `test_nearby.py` – `find_nearby` and `get_awo_details`

Offline. Edge cases run on a small Turtle snippet (origin at postal code 99991, facilities at
0, 0.56, 1.5 and 3 km, one without coordinates, offers and a provider); the directory check
runs on `data/directory.ttl`. `NoQueryClient` fails if a query is sent, for inputs that must be
rejected in Python.

| Test | Checks |
|---|---|
| `test_haversine_one_degree_of_latitude` | 1° of latitude ≈ 111.19 km |
| `test_bounding_box_contains_the_whole_circle` (×3) | every point exactly `radius_km` away (24 bearings, at 0°, 52.5° and 70° latitude) lies inside the box; the box is rounded outward |
| `test_matches_terms` (×8) | comma-separated terms match any; case-insensitive; `ß` in the data matches `ss`; empty query matches |
| `test_accessibility_flag` (×4) | "barrierefrei" → True, "nicht barrierefrei" → False, missing → None |
| `test_source_page_decodes_caritas_redirects` | relative `/search.ashx?…&u=` links become the real Caritas URL |
| `test_split_values` | `"; "`-joined values become a list |
| `test_resolve_location_from_coordinates_sends_no_query` | `"lat,lon"` resolves in Python |
| `test_resolve_location_rejects_bad_input_without_query` (×6) | street names, wrong-length postal codes and out-of-range coordinates → None, no query sent |
| `test_resolve_location_from_postal_code_averages_its_addresses` | origin = average of the postal code's addresses with coordinates |
| `test_resolve_location_unknown_postal_code` | unknown postal code → None |
| `test_find_nearby_returns_facilities_within_radius_nearest_first` | only facilities within the radius, sorted by distance |
| `test_find_nearby_excludes_facilities_without_coordinates` | facilities without coordinates never appear |
| `test_find_nearby_matches_offers_and_any_term` | terms match linked offers; several terms match any of them |
| `test_find_nearby_accessible_only_keeps_only_confirmed_accessible` | unknown and "nicht barrierefrei" are excluded |
| `test_find_nearby_limit_and_total` | `limit` cuts the list; `total_found` counts all matches |
| `test_find_nearby_clamps_radius` | radius is kept between 0.1 and 50 km |
| `test_find_nearby_unresolvable_location` | unresolvable location → `error`, no results |
| `test_get_awo_details_known_facility` | address, contacts, provider, decoded source link, map link and offers |
| `test_get_awo_details_facility_without_offers` | no offers → `[]`; address without street |
| `test_get_awo_details_unknown_iri` | unknown IRI or a service IRI → None |
| `test_get_awo_details_rejects_malformed_iri_without_query` (×4) | foreign, quote-breaking, spaced or empty IRIs → None, no query sent |
| `test_find_nearby_matches_independent_distance_check` (×2) | on `directory.ttl`, the result set equals facilities within the radius computed directly from the graph's triples |

### `test_repository.py` – `DataRepository` (reference implementation)
| Test | Checks |
|---|---|
| `test_count_facilities_is_case_insensitive` (×3) | Berlin/berlin/BERLIN == independent count from CSVs |
| `test_count_facilities_unknown_city_is_zero` | unknown city → 0 |
| `test_count_facilities_empty_string_is_zero` | `""` matches nothing (facilities without an address are not counted; was a bug, fixed) |
| `test_count_equals_search_length` | `count_facilities` and `search_facilities` agree |
| `test_search_facilities_result_shape_and_city` | result keys; every result is in the requested city |
| `test_search_facilities_skips_facilities_without_address` | missing/dangling address IRIs are skipped, no crash |
| `test_get_facility_details_partial_case_insensitive` | partial lower-case name finds the facility |
| `test_get_facility_details_shape_and_address` | detail keys + nested address present |
| `test_get_facility_details_unknown_name_is_empty` | no match → `[]` |
| `test_get_facility_details_treats_query_literally` | `".*"` is not a regex; `"(HLS6)"` works |
| `test_get_facility_details_includes_provider_when_linked` | provider attached via parentOrganization |
| `test_search_services_count_matches_csv` (×4) | name/category/audience substring matches == CSV count |
| `test_search_services_result_shape` | each result has iri, name, category, audience |
| `test_search_services_no_match_is_empty` | no match → `[]` |
| `test_detect_duplicates_clean_data_reports_nothing` | real data has no exact duplicates |
| `test_detect_duplicates_finds_injected_duplicate` | an injected duplicate row is found with `occurrences == 2` |
| `test_check_completeness_structure_and_ranges` | rows/columns/cells correct, percentages in 0–100 |
| `test_check_completeness_counts_blank_strings_as_missing` | NaN, `""` and `"   "` all count as missing |
| `test_check_completeness_missing_cells_sum_matches_columns` | dataset total == sum of columns |
| `test_statistics_dataset_sizes` | sizes == CSV row counts |
| `test_statistics_city_counts_agree_with_count_facilities` | stats and count tool agree |
| `test_statistics_relationships_add_up` | with + without address/provider == facility total |
| `test_compare_facilities_returns_both_sides` | both searches returned in order, each with a match |
| `test_compare_facilities_unknown_name_gives_empty_matches` | unknown facility → empty matches |

## Layer 2 – MCP protocol and end-to-end tests (`tests/protocol/`)

Talks to the real `server.py` through an in-memory MCP client (plus one stdio launch).
**Offline:** `tests/protocol/conftest.py` swaps the server's SPARQL client for
`LocalSparqlClient` on `data/directory.ttl`, so every tool runs its real `.rq` queries without
any request to the endpoint. The stdio launch only lists tools, so it sends no queries either.
`test_server.py` checks the MCP plumbing for every tool. `test_tools_e2e.py` checks each
feature end to end: what a client gets over MCP is compared with facts read directly from
the graph's triples (rdflib, not the `.rq` files).

### `test_server.py` – MCP plumbing

| Test | Checks |
|---|---|
| `test_baseline_tools_are_listed` | none of the 13 tools in `SMOKE_ARGS` disappeared |
| `test_every_listed_tool_has_smoke_args` | **fails when someone adds a tool without registering it in `SMOKE_ARGS`** – the prompt to add tests |
| `test_tool_metadata_is_llm_friendly` (×13) | docstring ≥ 20 chars, valid object schema, required ⊆ properties |
| `test_tool_call_succeeds` (×13) | call with valid args returns no MCP error and non-empty output |
| `test_tool_returns_valid_json_without_nan` (×12) | output parses as JSON; no bare `NaN` (`count_facilities` returns a plain number and is excluded) |
| `test_umlauts_are_not_escaped` | `ensure_ascii=False` works end-to-end |
| `test_missing_required_argument_is_an_error` | error names the missing argument |
| `test_wrong_argument_type_is_an_error` | wrong type rejected |
| `test_unknown_tool_is_an_error` | unknown tool → error |
| `test_server_starts_over_stdio` | `python server.py` starts and completes the MCP handshake |

### `test_tools_e2e.py` – two end-to-end tests per feature

Each tool and the `find_help` prompt has two tests named `test_e2e_<feature>_…`. Expected
values come straight from `data/directory.ttl` (or, for duplicates, a small Turtle snippet
the server is switched to for one call).

| Test | Checks |
|---|---|
| `test_every_feature_has_two_e2e_tests` | **fails when a tool or prompt has fewer than two `test_e2e_<feature>_…` tests** |
| `test_e2e_count_facilities_matches_graph` | `count_facilities(Berlin)` == facilities whose address is in Berlin in the graph |
| `test_e2e_count_facilities_is_case_insensitive_and_exact` | BERLIN, berlin-mitte, Atlantis: counts equal the graph's; Berlin-Mitte is not part of Berlin |
| `test_e2e_search_facilities_returns_exactly_the_city_facilities` | IRIs == the graph's Berlin facilities, none twice |
| `test_e2e_search_facilities_fields_come_from_the_graph` | Berlin-Mitte: name, street, postal code, city, phone, email, homepage == the graph's values |
| `test_e2e_get_facility_details_partial_name_finds_every_match` | `BERATUNG` finds exactly the facilities whose name contains "beratung" |
| `test_e2e_get_facility_details_includes_address_and_provider` | Drehscheibe: address and provider (IRI, name, homepage) == the graph's links |
| `test_e2e_compare_facilities_equals_two_detail_lookups` | result == two `get_facility_details` calls, both non-empty |
| `test_e2e_compare_facilities_keeps_order_and_reports_unknown_as_empty` | order kept; an unknown name gives `matches: []`, the other side is still found |
| `test_e2e_search_services_matches_name_category_or_audience` | `MEDIKAMENT` finds exactly the services with it in name, category or audience (incl. audience-only ones) |
| `test_e2e_search_services_no_match_and_quotes_stay_literal` | no match and a quote-breaking query (`") or true or ("`-style) both give `[]` |
| `test_e2e_find_social_help_matches_the_need_with_phones_first` | addiction: `total_matches` == the graph's services matching the need's terms; every result on topic; phone numbers first |
| `test_e2e_find_social_help_postal_prefix_and_unknown_need` | prefix 109 narrows the debt results and every result starts with 109; "pizza" returns the valid needs |
| `test_e2e_generate_statistics_dataset_sizes_match_graph` | dataset sizes == entities per RDF class in the graph |
| `test_e2e_generate_statistics_city_counts_agree_with_count_facilities` | every `facilities_by_city` entry == `count_facilities` for that city |
| `test_e2e_check_completeness_rows_match_dataset_sizes` | rows == dataset sizes; IRI never missing; missing cells == sum of columns |
| `test_e2e_check_completeness_missing_counts_match_graph` | every facility column: missing == facilities without a non-blank value in the graph |
| `test_e2e_detect_duplicates_directory_is_clean` | directory.ttl → `{}` |
| `test_e2e_detect_duplicates_finds_injected_duplicate` | snippet with two identical facilities and one different → one group with exactly the two IRIs |
| `test_e2e_list_providers_lists_every_provider` | IRIs == the graph's named providers; sorted by name |
| `test_e2e_list_providers_homepage_and_address_come_from_the_graph` | homepage and address of each provider == the graph's values |
| `test_e2e_search_by_postal_code_returns_exactly_that_area` | 10115: IRIs == facilities with that postal code in the graph |
| `test_e2e_search_by_postal_code_partial_or_unknown_finds_nothing` | 4 or 6 digits, unknown code or a quote-breaking input → `[]` |
| `test_e2e_records_to_fix_first_ranks_only_the_city` | every Berlin facility ranked once; bucket and priority counts add up; ranks 1…n; high → medium → low |
| `test_e2e_records_to_fix_first_bucket_filter_and_provider_batches` | `bucket=scope_check` returns exactly that bucket; provider batches cover every facility except scope-check/junk |
| `test_e2e_find_nearby_matches_distances_from_the_graph` | 13353, 1 km: origin == average of its addresses; results == facilities within 1 km by haversine on the graph; distances match; nearest first |
| `test_e2e_find_nearby_unresolvable_location_reports_error` | a street name → JSON with `error` and no results |
| `test_e2e_get_awo_details_known_facility_matches_graph` | org-229a4e0b1081: name, phone, email, hours and address == the graph's; map link points at its coordinates |
| `test_e2e_get_awo_details_unknown_iri_is_a_message_not_an_error` | unknown IRI → "No facility found" text, not an MCP error |
| `test_e2e_find_help_prompt_is_listed_and_renders` | `find_help` is listed with optional `situation`/`location`, renders with the inputs and tool names, has no unfilled placeholders, and says "not given yet" without inputs |
| `test_e2e_find_help_prompt_only_uses_tools_and_arguments_that_exist` | the tools, `find_nearby` arguments and `source_url` field the prompt names all exist on the server |

## Layer 3 – SPARQL API (`tests/api/test_sparql.py`)

Integration tests: real `.rq` files, real `SparqlClient`, the live endpoint
(`$SPARQL_ENDPOINT`) and the real MCP server. API, naming schema and limits are explained in
`QUERIES.md`. All tests are marked `api` and are **skipped** if an `ASK {}` probe fails.
They run only when triggered by hand (`.github/workflows/live-api.yml` or `pytest -m api tests`).
The live data is the whole federated directory (~37k facilities, all providers),
so numbers differ from the AWO CSVs. These tests therefore check consistency, not fixed
numbers.

To keep the load on the public endpoint low, each query is sent **once per test run**:
`CachingSparqlClient` keeps the result of every query, and `mcp_call_once` keeps the result
of every (tool, arguments) MCP call. The protocol layer shares these results. A full run
of layers 2 and 3 sends about 47 requests, one at a time (~50 s; before caching it was
115 requests and ~2 min). Each heavy query (completeness, statistics, duplicates) runs
twice: once inside the MCP server and once in the test client to compare against.
Reference counts come from a differently shaped query
(`list_facility_cities_by_city_substring.rq`: broad substring match, exact city match done
in Python).

| Test | Checks |
|---|---|
| `test_count_matches_independent_query` (×3) | Berlin, München, Köln: `count_facilities` == count from the reference query (and > 0) |
| `test_city_match_is_case_insensitive` | Berlin/berlin/BERLIN give the same count |
| `test_unknown_city_returns_zero` | unknown city → 0 |
| `test_query_injection_does_not_widen_match` | a city containing `") or true or ("` returns 0: the input stays inside the literal |
| `test_mcp_count_facilities_returns_reference_count` | MCP call `count_facilities(Berlin)` == reference count |
| `test_search_facilities_matches_count_and_reference` | `search_facilities(Berlin)` returns exactly the reference facilities, as many as `count_facilities` |
| `test_search_facilities_result_shape_and_city` | 8 keys per result; every result is in Berlin (any case) |
| `test_get_facility_details_known_facility` | Drehscheibe: names contain the query; org-00416a783a9b found with Berlin address and SPI provider |
| `test_get_facility_details_unknown_name_is_empty` | unknown name → `[]` |
| `test_search_services_every_result_matches` | every service contains "suchtberatung" in name, category or audience; no service twice |
| `test_detect_duplicates_structure` | only known datasets; each group has `occurrences == len(iris) ≥ 2` and no IRI column |
| `test_check_completeness_consistent` | rows == dataset sizes; IRI never missing; cells and missing counts add up; percentages 0–100 |
| `test_generate_statistics_consistent` | with + without address/provider == facility total; Berlin in `facilities_by_city` == `count_facilities`; per-provider and per-category sums are plausible |
| `test_compare_facilities_equals_two_detail_lookups` | both sides == `get_facility_details` for each name, both non-empty |
| `test_mcp_tool_returns_client_result` (×10) | every tool called over MCP returns exactly what `SparqlClient` returns (JSON round trip) |
| `test_postal_code_origin_is_where_the_postal_code_is` | 10115 resolves to central Berlin |
| `test_find_nearby_matches_independent_distance_check` (×2) | 10115 (1 km) and central Munich (1.5 km): result count == facilities within the radius from a plain coordinate query with distances in Python; results nearest first |
| `test_find_nearby_query_only_narrows` | `query="Sucht"` finds some but not more than without a query |
| `test_get_awo_details_known_facility` | org-229a4e0b1081 is vista WIGWAM Connect in Berlin, with a map link |
| `test_get_awo_details_agrees_with_find_nearby` | details of the nearest result have the same name and address |
| `test_get_awo_details_unknown_iri` | unknown IRI → None |

## Layer 4 – Connection smoke (`tests/llm/test_connection.py`)
| Test | Checks |
|---|---|
| `test_lists_models` | `GET /api/models` → 200 with ≥ 1 model (URL, API key, Ollama link) |
| `test_chat_completion` | a plain chat reply comes back (HTTP status + body shown on failure) |

## Layer 5 – Tool-calling evals (`tests/evals/`)

One test per **(model × case)**, repeated `--runs` times. A model gets the prompt plus the
real server's tool schemas, its tool calls are executed on the real MCP server, results are
fed back, and the outcome is scored. A case passes if the share of passing runs ≥
`--pass-threshold`.

Each failed run is labelled with the **stage** where it broke:

1. `model request failed` – HTTP/connection problem (status + body shown)
2. `model did not call a tool` – answered from memory
3. `model called a tool that does not exist`
4. `wrong tool chosen` – expected X, got Y
5. `wrong tool arguments` – which argument, what was expected
6. `tool execution returned an error` – the MCP tool itself failed
7. `model gave no final answer`
8. `final answer missing expected content` – e.g. the real number from the tool

Cases (`tests/evals/cases.json`): **two per tool**, written the way real users ask (German
and English, everyday wording, some needing optional arguments). Only the model's **first**
tool call is scored.

| Tool | Cases | What the second case adds |
|---|---|---|
| `count_facilities` | `count-berlin`, `count-muenchen-german` | German question; city must stay "München" (not "Munich") |
| `search_facilities` | `search-facilities-berlin`, `search-facilities-koeln-german` | German, asks for a list with contacts (list, not count) |
| `get_facility_details` | `facility-details`, `facility-details-who-runs-it` | quoted name in a casual question about the provider |
| `search_services` | `search-services-sucht`, `search-services-catalogue-pflege` | catalogue search by a maintainer, not a person seeking help |
| `find_social_help` | `find-help-debt`, `find-help-addiction-english` | need stated indirectly in English ("alcohol problem" → `addiction`) |
| `detect_duplicates` | `duplicates`, `duplicates-before-publishing` | "entered twice" instead of "duplicate" |
| `check_completeness` | `completeness`, `completeness-missing-phone-german` | German question about one column (phone) |
| `generate_statistics` | `statistics`, `statistics-top-city-and-category` | a concrete question the statistics answer, without the word "statistics" |
| `compare_facilities` | `compare`, `compare-side-by-side` | "side by side", argument order kept |
| `list_providers` | `list-providers`, `list-providers-german` | German "Träger" |
| `search_by_postal_code` | `postal-code-exact-area`, `postal-code-german` | must pick the exact postal code search, not `find_nearby` |
| `records_to_fix_first` | `fix-first-berlin`, `fix-first-outreach-by-provider` | optional `group_by="provider"` for provider outreach |
| `find_nearby` | `nearby-postal-code`, `nearby-coordinates` | coordinates instead of a postal code |
| `get_awo_details` | `awo-details-by-iri`, `awo-details-accessibility` | accessibility question; answer must contain the street |

`tests/evals/test_cases.py` checks the cases **offline** (no LLM, runs in CI with layers 1+2):

| Test | Checks |
|---|---|
| `test_eval_case_ids_are_unique` | no two cases share an id |
| `test_every_tool_has_two_eval_cases` | **fails when a tool has fewer than two cases in `cases.json`** |
| `test_eval_case_expects_a_valid_call` (×1 per case) | the expected tool exists, takes every expected argument, and runs with them on the offline server without an MCP error |

### Testing a new feature
1. Add valid arguments to `SMOKE_ARGS` in `tests/protocol/test_server.py`.
   Add two end-to-end tests named `test_e2e_<tool>_…` to `tests/protocol/test_tools_e2e.py`.
2. Put the query in `sparql_queries/` (naming schema in `QUERIES.md`), add a `SparqlClient`
   method, and add tests: offline ones in `tests/unit/` (`make_sources("""<Turtle>""")` or
   `LocalSparqlClient(load_graph(...))`) and live ones in `tests/api/`.
3. Add two entries to `tests/evals/cases.json` (realistic prompts; `test_cases.py` enforces two):
   ```json
   {"id": "my-feature", "prompt": "Natural-language question",
    "expect_tool": "my_tool", "expect_args": {"param": "substring"},
    "answer_contains": ["optional text the final answer must contain"]}
   ```
   `expect_args` values match case-insensitively as substrings.
4. Add a row for each new test to the tables in this file (the dashboard shows it as *Expected*).
5. Run `pytest -m llm tests/evals --models all --runs 3`.

## CI

* `.github/workflows/tests.yml` – layers 1+2 on every push/PR, GitHub-hosted, free,
  **offline** (`pytest -m "not llm and not api"`: no request to the SPARQL endpoint).
* `.github/workflows/live-api.yml` – layer 3, **manual** (Actions → "Live SPARQL API tests" →
  Run workflow; the endpoint can be changed there). ~47 requests to the endpoint, one at a time.
* `.github/workflows/llm-evals.yml` – layers 4+5, **manual** (Actions → "LLM evals" →
  Run workflow; choose models, runs, threshold). Runs on a self-hosted runner because
  Open WebUI is on `localhost`. Uploads `eval-report` as an artifact.

### Making your Mac the runner
1. GitHub repo → Settings → Actions → Runners → **New self-hosted runner** → macOS / ARM64.
   GitHub shows the exact download + `./config.sh --url … --token …` commands (the token is
   single-use and shown only there). Accept the default labels (`self-hosted`, `macOS`).
2. Start it: `./run.sh` in a terminal, or install as a service with `./svc.sh install && ./svc.sh start`
   (macOS: runs only while you are logged in).
3. Settings → Secrets and variables → Actions:
   * secret `OPENWEBUI_API_KEY` – your key (ideally from a dedicated "tester" Open WebUI user)
   * variable `OPENWEBUI_URL` – `http://localhost:3000` (default)
   * variable `PYTHON_BIN` – a Python 3.11, e.g. `/opt/homebrew/Caskroom/miniconda/base/envs/mcp/bin/python`
4. Keep the Mac awake (`caffeinate -s`) with Open WebUI/Ollama running.
5. Teammates with write access trigger runs from the Actions tab; the jobs run on your Mac
   with your key, so only add trusted collaborators, keep the repo private (or require
   approval for outside contributors), and keep the evals `workflow_dispatch`-only.
