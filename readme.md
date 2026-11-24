# tbdcca.com

This is a complete static mirror of the website [tbdcca.com](https://tbdcca.com).

## Archival Process

### 1. Initial Mirror

The repository was initially created using the following `wget` command:
```bash
wget --mirror --convert-links --adjust-extension --page-requisites --no-parent --output-file=tbdcca.com.log --domains=tbdcca.com https://tbdcca.com
```

### 2. Pulling Missing Pages & Relative Links (`pull_missing_pages.py`)

Because Webflow generated several project links pointing to `www.tbdcca.com` or `http://www.tbdcca.com` instead of `tbdcca.com`, the initial `wget` crawl skipped 51 project pages due to the strict `--domains=tbdcca.com` filter. Additionally, `wget --convert-links` prepended domain paths inside inline CSS `background-image` quotes on the downloaded project pages.

The [`pull_missing_pages.py`](file:///Users/ephetteplace/Code/warc/tbdcca.com/pull_missing_pages.py) downloads files from the sitemap and fixes internal links.

```bash
# Dry run: view what would be downloaded or changed
python3 pull_missing_pages.py --dry-run
# Run full pull and link normalization
python3 pull_missing_pages.py
# Re-normalize links without re-downloading
python3 pull_missing_pages.py --skip-download
```

### 3. Pulling CDN Images & Assets (`pull_cdn_images.py`)

All images, banners, icons, stylesheets, scripts, and fonts originally resided on external CDNs (`cdn.prod.website-files.com` and `d3e54v103j8qbb.cloudfront.net`).

The [`pull_cdn_images.py`](file:///Users/ephetteplace/Code/warc/tbdcca.com/pull_cdn_images.py) script automates:
1. Discovering all 2,277+ unique CDN assets referenced in `src`, `srcset`, inline CSS `background-image`, `link` icons, `meta` tags, and shared Webflow stylesheets.
2. Downloading all assets in parallel using `wget` with keep-alive connections into the host-based directory structure (`cdn.prod.website-files.com/` and `d3e54v103j8qbb.cloudfront.net/`).
3. Rewriting all CDN URLs across all HTML and CSS files to be relative:
   - Root HTML files -> `cdn.prod.website-files.com/...`
   - Project HTML files -> `../cdn.prod.website-files.com/...`
   - Webflow shared CSS -> relative font/image paths `../...`
4. Removing redundant external preconnect tags so browsers make zero external network requests.

```bash
# Dry run: view assets to download and files to rewrite
python3 pull_cdn_images.py --dry-run
# Run parallel download (default: 8 workers) and rewrite URLs
python3 pull_cdn_images.py --concurrency 8
# Re-rewrite URLs without re-downloading
python3 pull_cdn_images.py --skip-download
```

© 2026 California College of the Arts.
