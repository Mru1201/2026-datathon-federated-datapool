# Testing

Five layers, fastest first. Every assertion carries a message that says **what was
checked, what was expected, what was found, and where** (dataset / tool / model /
case), so a red test tells you where to look without a debugger.

| Layer | Folder | Needs | Runs in CI |
|---|---|---|---|
| 1. Unit | `tests/unit/` | nothing | every push/PR (hosted runner) |
| 2. MCP protocol | `tests/protocol/` | nothing (SPARQL endpoint for the `count_facilities_with_api` smoke calls) | every push/PR (hosted runner) |
| 3. SPARQL API | `tests/api/` | SPARQL endpoint (live tests skip if unreachable) | every push/PR (hosted runner) |
| 4. Connection smoke | `tests/llm/` | Open WebUI + API key | manual (self-hosted runner) |
| 5. Tool-calling evals | `tests/evals/` | Open WebUI + API key | manual (self-hosted runner) |

## Running

```bash
conda activate mcp
pip install -r requirements-dev.txt          # once

pytest -m "not llm"                           # layers 1-3, ~10 s, needs the SPARQL endpoint
pytest tests/api                              # layer 3 only: SPARQL queries + count_facilities_with_api
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

Expected values are computed from the raw CSVs with the `csv` module, independent of
the code under test. Edge cases use tiny synthetic datasets (`tests/helpers.py:make_repo`).

### `test_loader.py` – `DataLoader`
| Test | Checks |
|---|---|
| `test_load_all_returns_four_datasets` | keys are exactly einrichtung, adresse, angebot, traeger |
| `test_row_count_matches_csv` (×4) | loaded rows == rows in the CSV file (nothing lost/added) |
| `test_required_columns_present` (×4) | columns that `data_repository.py` reads exist |
| `test_iri_is_unique_and_filled` (×4) | `iri` never empty, never duplicated |
| `test_umlauts_survive_loading` | "Lübecker" is intact (encoding) |
| `test_missing_directory_raises_clear_error` | missing data dir → `FileNotFoundError` naming the CSV |
| `test_facility_address_references_resolve` | every facility address IRI exists in `adresse` |
| `test_facility_provider_references_resolve` | every facility provider IRI exists in `traeger` |

### `test_repository.py` – `DataRepository`
| Test | Checks |
|---|---|
| `test_count_facilities_is_case_insensitive` (×3) | Berlin/berlin/BERLIN == independent count from CSVs |
| `test_count_facilities_unknown_city_is_zero` | unknown city → 0 |
| `test_count_facilities_empty_string_is_zero` | **xfail (known bug)**: `""` matches facilities without an address. Remove the `xfail` once fixed |
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

## Layer 2 – MCP protocol tests (`tests/protocol/test_server.py`)

Talks to the real `server.py` through an in-memory MCP client (plus one stdio launch).

| Test | Checks |
|---|---|
| `test_baseline_tools_are_listed` | none of the 9 baseline tools disappeared |
| `test_every_listed_tool_has_smoke_args` | **fails when someone adds a tool without registering it in `SMOKE_ARGS`** – the prompt to add tests |
| `test_tool_metadata_is_llm_friendly` (×9) | docstring ≥ 20 chars, valid object schema, required ⊆ properties |
| `test_tool_call_succeeds` (×9) | call with valid args returns no MCP error and non-empty output (`count_facilities_with_api` calls the live endpoint) |
| `test_tool_returns_valid_json_without_nan` (×7) | output parses as JSON; no bare `NaN` (the two `count_facilities*` tools return a plain number and are excluded) |
| `test_count_facilities_returns_correct_number` | MCP result == independent CSV count |
| `test_umlauts_are_not_escaped` | `ensure_ascii=False` works end-to-end |
| `test_search_services_output_matches_csv` | tool output size == CSV count |
| `test_missing_required_argument_is_an_error` | error names the missing argument |
| `test_wrong_argument_type_is_an_error` | wrong type rejected |
| `test_unknown_tool_is_an_error` | unknown tool → error |
| `test_server_starts_over_stdio` | `python server.py` starts and completes the MCP handshake |

## Layer 3 – SPARQL API (`tests/api/test_sparql.py`)

Tests the SPARQL client (`src/sparql_client.py`), the query files in `sparql_queries/`
(naming schema, API and limits explained in `QUERIES.md`) and the
`count_facilities_with_api` tool. The first five tests run offline. The rest query the live
endpoint (`$SPARQL_ENDPOINT`) and are **skipped** if an `ASK {}` probe fails. Expected counts
come from a differently shaped reference query
(`list_facility_cities_by_city_substring.rq`: broad substring match, exact city match
done in Python), not from the code under test. The endpoint holds the whole federated
directory (all providers, not just AWO), so these counts differ from the CSV-based `count_facilities`.

| Test | Checks |
|---|---|
| `test_escape_literal_escapes_quotes_and_backslashes` | quotes, backslashes and newlines are escaped for a SPARQL string literal |
| `test_load_query_embeds_escaped_city` | `load_query` fills `{{city}}` in `count_facilities_by_city.rq` with the escaped value |
| `test_load_query_without_required_param_raises` | a missing placeholder value raises `ValueError` naming the parameter |
| `test_query_files_follow_naming_convention` (×1 per `.rq` file) | file name matches `<action>_<entity>_by_<filter>.rq` and has `# Params:` and `# Used by:` header comments |
| `test_count_matches_independent_query` (×3) | Berlin, München, Köln: `count_facilities` == count from the reference query (and > 0) |
| `test_city_match_is_case_insensitive` | Berlin/berlin/BERLIN give the same count |
| `test_unknown_city_returns_zero` | unknown city → 0 |
| `test_query_injection_does_not_widen_match` | a city containing `") or true or ("` returns 0: the input stays inside the literal |
| `test_mcp_tool_returns_api_count` | MCP call `count_facilities_with_api(Berlin)` == reference count |

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

Cases (`tests/evals/cases.json`): `count-berlin`, `search-facilities-berlin`,
`facility-details`, `search-services-sucht`, `duplicates`, `completeness`, `statistics`, `compare`.

### Testing a new feature
1. Add valid arguments to `SMOKE_ARGS` in `tests/protocol/test_server.py`.
2. Add unit tests for the repository logic in `tests/unit/`. For a SPARQL-backed tool, put
   the query in `sparql_queries/<action>_<entity>_by_<filter>.rq`, load it with
   `load_query(...)`, and add tests in `tests/api/`.
3. Add an entry to `tests/evals/cases.json`:
   ```json
   {"id": "my-feature", "prompt": "Natural-language question",
    "expect_tool": "my_tool", "expect_args": {"param": "substring"},
    "answer_contains": ["optional text the final answer must contain"]}
   ```
   `expect_args` values match case-insensitively as substrings.
4. Add a row for each new test to the tables in this file (the dashboard shows it as *Expected*).
5. Run `pytest -m llm tests/evals --models all --runs 3`.

## CI

* `.github/workflows/tests.yml` – layers 1–3 on every push/PR, GitHub-hosted, free.
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
