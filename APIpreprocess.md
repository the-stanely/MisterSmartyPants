# API Preprocess Plan

MisterSmartyPants currently treats most current-information requests as a web search problem:

```text
user question -> decider -> query builder -> DDGS -> fetch URLs -> Trafilatura -> rank -> summarize -> answer
```

That works for articles, but it is the wrong tool for sites that already expose structured data. The API preprocess layer should run after the search decider and query builder, then bypass DDGS when the built query clearly maps to a structured API.

There is a problem with search because many sites block scraping, or render in a way that scraping is not possible.

## Goal

Use official or stable public APIs for query types where HTML search and extraction are unreliable.

The API path should produce the same kind of source material the final LLM already understands:

```text
title
url
published/date
source/API name
content
```

Then the existing summarization/final-answer path can stay mostly unchanged.

## Placement

Recommended order:

```text
user question
  -> slash command handling
  -> search enabled?
  -> YES/NO search decider
  -> if YES: answer from model knowledge
  -> if NO: query builder
  -> API classifier on built query
  -> if API route matches strongly: API fetch
  -> otherwise: DDGS search using built query
  -> summarize/process retrieved data
  -> final assistant answer, unless /llm-off
```

The key idea is that the first decider gates all external retrieval. The API classifier should not decide whether retrieval is needed. It should only decide whether a retrieval request is better served by an API than by DDGS.

Example:

```text
Describe Texas weather in the winter of 2021.
  -> decider says YES
  -> no API classifier
  -> answer from model knowledge

What is the weather in Iowa City today?
  -> decider says NO
  -> query builder
  -> API classifier sees weather forecast query
  -> Open-Meteo API
```

Important behavior:

- API preprocess should run only after the decider says external information is needed.
- API preprocess should receive the built query, not the raw user prompt.
- If an API rule matches but the API request fails, fail visibly. Do not silently fall back to DDGS.
- If no API rule matches, continue to DDGS using the built query.
- `/search-off` should bypass API preprocess too, because it means "send prompt directly to the LLM."
- `/llm-off` should not disable API preprocess.
- `/prompt-on` should show API request URL, normalized response, and generated source text.

## Normalized Result Format

API adapters should return a payload shaped like the current search payload:

```json
{
  "api_source": "github",
  "fetched_pages": [
    {
      "title": "Repository: owner/name",
      "url": "https://github.com/owner/name",
      "published": "2026-06-08T12:34:56Z",
      "author": "owner",
      "extractor": "api",
      "content": "Human-readable API result text. [END EXCERPT]"
    }
  ]
}
```

This lets `format_search_data_for_prompt()` and summarization work with minimal change, though the source heading should eventually say "API result" instead of "web news search result" when appropriate.

## Routing Logic

Use deterministic pattern matching first. Avoid an LLM router until the hard cases justify it.

Each route should expose:

```python
class ApiRoute:
    name: str
    confidence: str  # "exact", "strong", "weak"
    match(search_query: str) -> RouteMatch | None
    fetch(match: RouteMatch) -> NormalizedApiPayload
```

Only `exact` and `strong` routes should bypass search automatically. `weak` routes should do nothing at first.

Because the search decider already filtered out historical/static/explanatory requests, the route matcher can stay focused on clean query terms and API-specific entity extraction.

## Useful API Routes

These routes are intended for URL-aware fetching after DDGS has already found candidate links. The fetcher should inspect the result URL, choose an API fetcher when the domain/path is recognized, and otherwise use the normal HTML + Trafilatura path.

## Public API Catalog

### GitHub

Use when DDGS returns:

```text
https://github.com/{owner}
https://github.com/{owner}/{repo}
https://github.com/{owner}/{repo}/issues
https://github.com/{owner}/{repo}/pulls
https://github.com/{owner}/{repo}/commits
```

API endpoints:

```text
GET https://api.github.com/users/{owner}
GET https://api.github.com/users/{owner}/repos?sort=updated&per_page=10
GET https://api.github.com/repos/{owner}/{repo}
GET https://api.github.com/repos/{owner}/{repo}/commits?per_page=10
GET https://api.github.com/repos/{owner}/{repo}/issues?state=open&per_page=10
GET https://api.github.com/repos/{owner}/{repo}/pulls?state=open&per_page=10
GET https://api.github.com/search/repositories?q={query}&sort=updated&order=desc&per_page=10
```

Best for:

- repository updates
- recent commits
- open issues/pull requests
- repository metadata
- user public repositories

### arXiv

Use when DDGS returns:

```text
https://arxiv.org/abs/{id}
https://arxiv.org/pdf/{id}
https://arxiv.org/html/{id}
```

Official API:

```text
GET https://export.arxiv.org/api/query?id_list={id}
GET https://export.arxiv.org/api/query?search_query=all:{query}&start=0&max_results=10&sortBy=submittedDate&sortOrder=descending
```

Best for:

- physics
- cosmology
- mathematics
- computer science
- "instability of the universe" / cosmological model papers
- dark energy, cosmological constant, general relativity, quantum gravity, etc.

For the universe-instability question, DDGS may find a `phys.org` article, but the API fetcher should prefer arXiv if a linked/preprint ID is present or if DDGS directly returns an arXiv result. The normalized content should include title, authors, published/updated dates, categories, abstract, arXiv ID, DOI if present, and PDF/page links.

### OpenAlex

Use when DDGS returns:

```text
https://openalex.org/W...
https://doi.org/{doi}
publisher article URLs with DOI metadata
```

API endpoints:

```text
GET https://api.openalex.org/works/{openalex_id}
GET https://api.openalex.org/works/https://doi.org/{doi}
GET https://api.openalex.org/works?search={query}&per-page=10&sort=publication_date:desc
```

Best for:

- broad scholarly search
- publication metadata
- authors/institutions
- citation counts
- DOI resolution

OpenAlex is useful when the source is scholarly but not arXiv-specific.

### Crossref

Use when DDGS returns:

```text
https://doi.org/{doi}
publisher pages with DOI in URL or metadata
```

API endpoints:

```text
GET https://api.crossref.org/works/{doi}
GET https://api.crossref.org/works?query={query}&rows=10&sort=published&order=desc
```

Best for:

- DOI metadata
- journal articles
- conference papers
- publication dates
- publisher links

Crossref is metadata-oriented. It usually will not provide full article text.

### PubMed / NCBI E-utilities

Use when DDGS returns:

```text
https://pubmed.ncbi.nlm.nih.gov/{pmid}/
https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/
```

API endpoints:

```text
GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={pmid}&retmode=json
GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml
GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={query}&retmode=json&retmax=10&sort=date
```

Best for:

- biomedical literature
- medical research papers
- PubMed abstracts
- article metadata

### Wikipedia / Wikimedia

Use when DDGS returns:

```text
https://en.wikipedia.org/wiki/{title}
https://*.wikipedia.org/wiki/{title}
```

API endpoints:

```text
GET https://en.wikipedia.org/api/rest_v1/page/summary/{title}
GET https://en.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=5&namespace=0&format=json
```

Best for:

- encyclopedia summaries
- stable background
- entity descriptions

Do not use this to override fresh news/search results for current status questions.

### Wikidata

Use when DDGS returns:

```text
https://www.wikidata.org/wiki/Q{id}
```

API endpoints:

```text
GET https://www.wikidata.org/wiki/Special:EntityData/Q{id}.json
GET https://www.wikidata.org/w/api.php?action=wbsearchentities&search={query}&language=en&format=json
```

Best for:

- structured facts about entities
- identifiers
- dates
- relationships
- links to official sites and external IDs

### PyPI

Use when DDGS returns:

```text
https://pypi.org/project/{project}/
```

API endpoint:

```text
GET https://pypi.org/pypi/{project}/json
```

Best for:

- Python package version
- release history
- project metadata
- project URLs
- vulnerabilities if returned

### npm Registry

Use when DDGS returns:

```text
https://www.npmjs.com/package/{package}
```

API endpoint:

```text
GET https://registry.npmjs.org/{package}
```

Best for:

- JavaScript package version
- release history
- package metadata

### crates.io

Use when DDGS returns:

```text
https://crates.io/crates/{crate}
```

API endpoint:

```text
GET https://crates.io/api/v1/crates/{crate}
```

Best for:

- Rust crate metadata
- latest version
- downloads
- repository links

### NuGet

Use when DDGS returns:

```text
https://www.nuget.org/packages/{package}
```

API endpoints:

```text
GET https://api.nuget.org/v3/registration5-semver1/{lowercase_package}/index.json
GET https://azuresearch-usnc.nuget.org/query?q=packageid:{package}&prerelease=false
```

Best for:

- .NET package metadata
- versions
- release dates

### Open-Meteo

Use when DDGS returns weather pages, or if a later API router handles weather directly:

```text
weather.com
wunderground.com
accuweather.com
forecast.weather.gov
```

API endpoints:

```text
GET https://geocoding-api.open-meteo.com/v1/search?name={place}&count=5&language=en&format=json
GET https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto
```

Best for:

- current weather
- forecasts
- simple no-key weather data

This one is less URL-driven than GitHub/arXiv/PyPI because DDGS weather URLs often point to commercial pages rather than a canonical entity. It may eventually need a query-based route.

### SEC EDGAR

Use when DDGS returns:

```text
https://www.sec.gov/...
https://www.sec.gov/Archives/edgar/data/{cik}/...
```

API endpoints:

```text
GET https://data.sec.gov/submissions/CIK{cik_10_digits}.json
GET https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_10_digits}.json
```

Best for:

- public company filings
- 10-K, 10-Q, 8-K metadata
- company financial facts

SEC requests require a responsible User-Agent header.

### ClinicalTrials.gov

Use when DDGS returns:

```text
https://clinicaltrials.gov/study/{nct_id}
```

API endpoint:

```text
GET https://clinicaltrials.gov/api/v2/studies/{nct_id}
GET https://clinicaltrials.gov/api/v2/studies?query.term={query}
```

Best for:

- clinical trial status
- trial conditions/interventions
- sponsors
- enrollment
- study dates

### openFDA

Use when DDGS returns:

```text
https://www.accessdata.fda.gov/...
https://api.fda.gov/...
```

API endpoints:

```text
GET https://api.fda.gov/drug/label.json?search={query}&limit=10
GET https://api.fda.gov/drug/event.json?search={query}&limit=10
GET https://api.fda.gov/device/event.json?search={query}&limit=10
```

Best for:

- drug labels
- adverse events
- device adverse events
- recalls, depending on endpoint

### Internet Archive

Use when DDGS returns:

```text
https://archive.org/details/{identifier}
```

API endpoint:

```text
GET https://archive.org/metadata/{identifier}
```

Best for:

- archived item metadata
- file lists
- publication info

### YouTube oEmbed

Use when DDGS returns:

```text
https://www.youtube.com/watch?v={id}
https://youtu.be/{id}
```

API endpoint:

```text
GET https://www.youtube.com/oembed?url={video_url}&format=json
```

Best for:

- title
- author/channel
- thumbnail

This does not provide transcript or comments.

### GitHub

Use for:

- "GitHub user X recent repository updates"
- "latest commits for owner/repo"
- "open issues for owner/repo"
- direct GitHub profile/repo URLs

Official docs:

- https://docs.github.com/rest
- https://docs.github.com/rest/repos/repos

Useful endpoints:

```text
GET https://api.github.com/users/{username}
GET https://api.github.com/users/{username}/repos?sort=updated&per_page=10
GET https://api.github.com/repos/{owner}/{repo}
GET https://api.github.com/repos/{owner}/{repo}/commits?per_page=10
GET https://api.github.com/repos/{owner}/{repo}/issues?state=open&per_page=10
```

Trigger examples:

```text
github user "the-stanely" recent repository updates
newest repository updates from GitHub user "the-stanely"
latest commits in stanely/MisterSmartyPants
https://github.com/the-stanely/MisterSmartyPants
```

Extraction logic:

- If prompt has `github.com/{owner}/{repo}`, use repo endpoints.
- If prompt has `github user "{name}"`, use user repos endpoint.
- Sort repositories by `updated_at`.
- Content should include repo name, description, pushed/updated dates, stars, forks, language, URL, and recent commit subjects if fetched.

### Weather

Use for:

- weather forecast
- current weather
- temperature, rain, snow, wind
- zip-code or city forecast

Good default API:

- Open-Meteo: https://open-meteo.com/
- Geocoding docs: https://open-meteo.com/en/docs/geocoding-api
- Forecast docs: https://open-meteo.com/en/docs

Useful endpoints:

```text
GET https://geocoding-api.open-meteo.com/v1/search?name={place}&count=5&language=en&format=json
GET https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto
```

Trigger examples:

```text
Iowa City weather forecast
weather in 52240 tomorrow
will it rain in Chicago this weekend
```

Extraction logic:

- Parse location after weather terms.
- Geocode first.
- If multiple locations match, pick the first for now and include the resolved name/country/admin area.
- Content should include current conditions and daily forecast.

### Wikipedia / Wikimedia

Use for:

- stable encyclopedia-style facts
- "who is", "what is", "tell me about" when a named entity is likely encyclopedic
- direct Wikipedia URLs

Official docs:

- MediaWiki Action API opensearch: https://www.mediawiki.org/wiki/API:Opensearch
- MediaWiki REST API: https://www.mediawiki.org/wiki/API:REST_API

Useful endpoints:

```text
GET https://en.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=5&namespace=0&format=json
GET https://en.wikipedia.org/api/rest_v1/page/summary/{title}
```

Trigger examples:

```text
who was Ringo Starr
what is the cosmological constant
tell me about Iowa City
```

Extraction logic:

- Use opensearch for title resolution.
- Fetch summary for the top title.
- Include page URL and extract.

Note:

- This should not replace search for "latest" requests about a person or event.

### Scholarly Research

Use for:

- recent papers
- DOI lookup
- PubMed/medical papers
- arXiv/cosmology/physics/math papers
- citations and academic metadata

Recommended APIs:

- OpenAlex: https://docs.openalex.org/
- Crossref REST API: https://www.crossref.org/documentation/retrieve-metadata/rest-api/
- NCBI E-utilities: https://www.ncbi.nlm.nih.gov/home/develop/api/
- arXiv API: https://info.arxiv.org/help/api/

Useful endpoints:

```text
GET https://api.openalex.org/works?search={query}&per-page=10&sort=publication_date:desc
GET https://api.crossref.org/works?query={query}&rows=10&sort=published&order=desc
GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={query}&retmode=json&retmax=10&sort=date
GET https://export.arxiv.org/api/query?search_query=all:{query}&start=0&max_results=10&sortBy=submittedDate&sortOrder=descending
```

Trigger examples:

```text
recent research disputing dark energy
papers about cosmological constant instability
new PubMed studies about metformin
find arXiv papers about transformer inference
```

Extraction logic:

- If prompt mentions PubMed, use NCBI.
- If prompt mentions arXiv or physics/math/cosmology, use arXiv and/or OpenAlex.
- If prompt includes a DOI, use Crossref DOI lookup.
- Otherwise OpenAlex is a good broad first choice.
- Content should include title, authors, publication date, venue, DOI/arXiv ID, abstract if available, and source URL.

### Package Registries

Use for:

- latest package version
- release metadata
- project URLs
- vulnerabilities where API exposes them

APIs:

- PyPI JSON API: https://docs.pypi.org/api/json/
- npm registry: https://registry.npmjs.org/{package}
- crates.io API: https://crates.io/api/v1/crates/{crate}
- NuGet search/registration APIs: https://learn.microsoft.com/nuget/api/overview

Useful PyPI endpoint:

```text
GET https://pypi.org/pypi/{project}/json
```

Trigger examples:

```text
latest version of trafilatura on PyPI
is requests package vulnerable
latest npm version of vite
```

Extraction logic:

- Detect package ecosystem from words: PyPI, pip, npm, crate, NuGet.
- Fetch package metadata.
- Include latest version, release date when available, project URLs, summary, license, vulnerabilities if returned.

### Government / Public Data

Use for:

- company filings
- economic data
- official medical/drug/device data
- clinical trials

Useful APIs:

```text
SEC EDGAR company submissions:
GET https://data.sec.gov/submissions/CIK{cik}.json

FRED economic data:
GET https://api.stlouisfed.org/fred/series/observations?series_id={series}&api_key={key}&file_type=json

openFDA:
GET https://api.fda.gov/drug/event.json?search={query}&limit=10

ClinicalTrials.gov:
GET https://clinicaltrials.gov/api/v2/studies?query.term={query}
```

Trigger examples:

```text
latest SEC filings for Microsoft
current CPI from FRED
clinical trials for glioblastoma
FDA adverse events for metformin
```

Notes:

- Some APIs require API keys or specific user-agent headers.
- These should be opt-in routes after the no-key routes are stable.

## First Implementation Targets

Start with the highest-value, lowest-risk routes:

1. GitHub user/repo route
2. Open-Meteo weather route
3. Wikipedia summary route
4. OpenAlex/arXiv scholarly route
5. PyPI package route

These cover many cases where generic search and Trafilatura are weak.

## Proposed Flow

```python
def run_query(query):
    if not search_enabled:
        return answer_direct(query)

    should_search = decide(query)
    if not should_search:
        return answer_from_memory(query, history)

    search_query = derive_search_query(query)

    api_result = try_api_preprocess(search_query)
    if api_result:
        result = api_result.to_search_payload_json()
    else:
        result = run_search(search_query, ...)

    if SUMMARIZE_EXCERPTS:
        result = summarize_search_result_excerpts(result, query)

    if not llm_enabled:
        print("[LLM: skipped]")
        return

    return answer_from_results(query, result, history)
```

## Matching Rules

### GitHub

```text
github.com/{owner}/{repo}
github user "{username}"
github user {username}
repository updates from GitHub user {username}
latest commits for {owner}/{repo}
```

### Weather

```text
\bweather\b
\bforecast\b
\btemperature\b
\brain\b
\bsnow\b
```

Require a location-like phrase. If no location is found, fail with "weather route matched but no location could be parsed."

### Wikipedia

```text
who is {entity}
who was {entity}
what is {entity}
tell me about {entity}
```

Do not trigger if the prompt contains recent/current/news/latest/today.

### Scholarly

```text
\bpaper(s)?\b
\bresearch\b
\bstudy\b
\bdoi\b
\barxiv\b
\bpubmed\b
```

Prefer arXiv for explicit arXiv or physics/math/cosmology terms. Prefer PubMed for explicit PubMed or biomedical terms.

### Package

```text
\bpypi\b
\bpip\b
\bnpm\b
\bcrates\.io\b
\bnuget\b
\blatest version\b
```

## Logging

Normal mode:

```text
[API: github, 812 ms, 5 sources]
```

Prompt debug mode:

```text
[API request: github]
GET https://api.github.com/users/the-stanely/repos?sort=updated&per_page=10

[API normalized source 1]
Title: Repository: the-stanely/MisterSmartyPants
URL: https://github.com/the-stanely/MisterSmartyPants
Published: 2026-06-08T...
Content:
...
```

## Failure Policy

No silent fallbacks.

If a route strongly matches and fails, show the failure:

```text
[API: github, failed]
GitHub API route matched "the-stanely", but the API returned 403 rate limit.
```

If a route does not match, continue to DDGS with the already-built query.

If a route weakly matches, do nothing for now.

## Open Questions

- Should API results skip summarization for already-short structured responses?
- Should API routes be controlled by `.env`, e.g. `API_PREPROCESS_ENABLED=1` and `API_ROUTES=github,weather,wikipedia`?
- Should API output use the same "WEB NEWS SEARCH RESULTS" prompt block, or should the final prompt say "CURRENT API DATA"?
- Should domain-specific API routes also be tried when DDGS returns a known domain URL, e.g. GitHub URL found by search?

## Recommendation

Implement `try_api_preprocess(search_query)` with only GitHub first.

GitHub is the clearest win:

- HTML extraction is poor for GitHub.
- The API is excellent.
- The matching rules are straightforward.
- The data is naturally current.

After GitHub works, add weather with Open-Meteo.
