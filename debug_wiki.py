from urllib.parse import urlparse
import requests

url = 'https://en.wikipedia.org/wiki/Python_(programming_language)'
parsed = urlparse(url)
print(f'netloc: {parsed.netloc}')
print(f'path: {parsed.path}')
path = parsed.path.strip('/')
print(f'stripped path: {path}')
wiki_prefix = 'wiki/'
print(f'startswith wiki/: {path.startswith(wiki_prefix)}')
if path.startswith(wiki_prefix):
    page_title = path[5:]
    print(f'page_title: {page_title}')
    
    # Try API call
    api_url = 'https://en.wikipedia.org/w/api.php'
    resp = requests.get(api_url, params={
        'action': 'query',
        'titles': page_title,
        'prop': 'extracts|info',
        'explaintext': True,
        'format': 'json',
        'redirects': 1,
    }, timeout=20)
    print(f'status: {resp.status_code}')
    data = resp.json()
    page_ids = list(data.get('query', {}).get('pages', {}).keys())
    print(f'pages: {page_ids}')
    if page_ids:
        page_id = page_ids[0]
        page = data['query']['pages'][page_id]
        print(f'page keys: {list(page.keys())}')
        print(f'title: {page.get("title", "")}')
        missing = 'missing' in page
        print(f'has missing: {missing}')
        if 'extract' in page:
            preview = page['extract'][:100]
            print(f'extract preview: {preview}')
