# SPARQL queries

The MCP tools ending in `_with_api` do not read the local CSVs. They query the live
**Federated directory of social support services in Germany** (SoSuSe, run by CorrelAid)
over SPARQL. Every query goes through the custom `SparqlClient` class in
`src/sparql_client.py`. Tools never build query strings themselves.

## The API

| | |
|---|---|
| Endpoint | `https://sosuse.correlaid.org/directory/sparql` (override with `$SPARQL_ENDPOINT`) |
| Protocol | SPARQL 1.1 over HTTP: `GET ?query=<urlencoded>` |
| Result format | `application/sparql-results+json` (also CSV/TSV, Turtle for CONSTRUCT/DESCRIBE) |
| Auth | none, public |
| Health check | `ASK {}` → `{"boolean": true}` |

The endpoint has a query UI with built-in examples (graph
`urn:directory:webapp/content/query-examples.ttl`, e.g. "Einrichtungen nach Name suchen",
"Einrichtungen im Kartenausschnitt", "Quellen einer Entität").

### Data model (default graph, ~475k triples)

All entities use IRIs under `https://civic-data.de/federated-directory#` (prefix `cdf:`).

| Class | Count | Main properties |
|---|---|---|
| `org:OrganizationalUnit` (facility, *Einrichtung*) | ~37,000 | `schema:name`, `schema:address`, `schema:telephone`, `schema:email`, `foaf:homepage`, `schema:description`, `schema:alternateName`, `schema:openingHours`, `schema:category`, `schema:availableService`, `schema:audience`, `schema:parentOrganization`, `schema:mainEntityOfPage`, `dct:modified` |
| `schema:PostalAddress` | ~26,000 | `schema:streetAddress`, `schema:postalCode`, `schema:addressLocality`, `schema:addressCountry`, `schema:latitude`, `schema:longitude` |
| `schema:Service` (offer, *Angebot*) | ~4,000 | `schema:name`, `schema:category`, `schema:provider` (→ facility), `schema:audience`, `schema:openingHours`, `schema:areaServed` |
| `schema:Organization` (provider, *Träger*) | 4 | `schema:name` |

Prefixes: `schema: <http://schema.org/>`, `org: <http://www.w3.org/ns/org#>`,
`foaf: <http://xmlns.com/foaf/0.1/>`, `dct: <http://purl.org/dc/terms/>`.

Named graphs hold the pipeline behind the directory (`urn:directory:data/pipeline/*`,
`urn:directory:data/provenance.ttl`, `urn:directory:config/*`). Query them with
`GRAPH <…> { … }` if you need to know where a record came from.

### What is possible

* Any read query: `SELECT`, `ASK`, `CONSTRUCT`, `DESCRIBE`, with aggregates (`COUNT`,
  `GROUP BY`), property paths (`schema:address/schema:addressLocality`), `FILTER`,
  `REGEX`, `CONTAINS`, `LCASE`, `OPTIONAL`, `GRAPH`.
* Counting, listing and joining facilities ↔ addresses ↔ services across all providers.
* Geographic queries via the `schema:latitude` / `schema:longitude` literals (bounding-box `FILTER`s).
* Provenance: which source a record came from (named graphs).

### What is not possible / limitations

* **Read-only.** Treat the endpoint as read-only; the MCP never sends updates.
* **Not AWO-only.** The directory federates all providers (mostly Caritas and DHS). AWO is a
  small part, so `count_facilities_with_api` ≠ CSV-based `count_facilities`. Only 39 facilities
  have a `schema:parentOrganization`, so filtering by provider is limited.
* **City names are not normalised.** `addressLocality` contains values like `Berlin-Mitte`,
  `Berlin- Tempelhof` or `Berl Berlin`. The exact match in `count_facilities_by_city.rq`
  counts only `Berlin` (any case). Districts and typos are not included.
* **Data quality:** not every facility has an address (~37.3k facilities, ~37.0k with one),
  some addresses lack coordinates, and several facilities may share one address.
* **No paging in the client yet.** Large `list_*` queries return everything at once. Add
  `LIMIT`/`OFFSET` in the query file when a tool needs paging.
* **`SparqlClient.query` parses JSON only**, so it is meant for `SELECT` and `ASK`.
  `CONSTRUCT`/`DESCRIBE` return RDF and would need a separate method.
* **Live dependency:** tools and the live tests in `tests/api/` fail (or skip) when the
  endpoint is down or slow (client timeout: 30 s).

## How a query runs: `SparqlClient`

```
MCP tool (server.py)              count_facilities_with_api(city)
  → SparqlClient method           sparql.count_facilities(city)
    → load_query(name, **params)  reads sparql_queries/count_facilities_by_city.rq,
                                  fills {{city}} with an escaped literal
    → SparqlClient.query(sparql)  GET <endpoint>?query=…, Accept: sparql-results+json
  ← parsed bindings → int / list / dict returned to the tool
```

* `load_query(name, **params)` loads `sparql_queries/<name>.rq` and replaces every
  `{{param}}` with the escaped value (`escape_literal`: `\`, `"`, newlines, tabs). A missing
  parameter raises `ValueError`.
* `SparqlClient(endpoint=None, timeout=30)` uses `$SPARQL_ENDPOINT` or the default endpoint.
* `SparqlClient.query(sparql)` runs any SPARQL string and returns the parsed JSON.
* One method per use case (e.g. `count_facilities`) turns the bindings into a plain Python value.

Placeholders are only safe **inside double-quoted string literals** (`"{{city}}"`). Never
put one where an IRI, number, variable or keyword belongs (e.g. `LIMIT {{n}}`). For those,
validate the value in Python first.

## Query files: naming schema

One query per file in `sparql_queries/`:

```
<action>_<entity>_by_<filter>.rq
```

| Part | Meaning | Values |
|---|---|---|
| `action` | what the query returns | `count` (one number), `list` (rows), `get` (one item), `ask` (yes/no) |
| `entity` | the main thing queried, plural | `facilities`, `services`, `providers`, `addresses`, `facility_cities`, … |
| `by_<filter>` | the parameter(s) it filters on | `by_city`, `by_name`, `by_postal_code`, `by_city_substring`, … |

All lower snake case. Each file starts with a header comment:

```sparql
# <what it returns, one line>
# Params: {{city}}
# Used by: <method / tool / test that uses it>
```

Apart from placeholders, files are plain SPARQL and can be pasted into the endpoint's
query UI. `test_query_files_follow_naming_convention` in `tests/api/test_sparql.py` fails
for any `.rq` file that does not match the schema or lacks the header.

| File | Returns | Used by |
|---|---|---|
| `count_facilities_by_city.rq` | `?count` of facilities in a city (case-insensitive exact match) | `SparqlClient.count_facilities` → `count_facilities_with_api` |
| `list_facility_cities_by_city_substring.rq` | `?facility ?city` rows whose city contains the text | `tests/api/test_sparql.py` (independent reference) |

## Adding a query-backed tool

1. Write `sparql_queries/<action>_<entity>_by_<filter>.rq` with the header, and add it to the table above.
2. Add a `SparqlClient` method that calls `self.query(load_query("<name>", ...))` and returns a plain value.
3. Add an `@mcp.tool()` in `server.py` named `<something>_with_api` that calls the method.
4. Add tests in `tests/api/`, register the tool in `SMOKE_ARGS`, and describe the tests in `TEST.md`.
