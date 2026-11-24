# tbdcca.com

This is a static mirror of the website [tbdcca.com](https://tbdcca.com).

## Archival Process

### Initial Mirror

The repository was initially created using the following `wget` command:
```bash
wget --mirror --convert-links --adjust-extension --page-requisites --no-parent --output-file=tbdcca.com.log --domains=tbdcca.com https://tbdcca.com
```

### Pulling Missing Pages & Relative Links (`pull_missing_pages.py`)

Because Webflow generated several project links pointing to `www.tbdcca.com` or `http://www.tbdcca.com` instead of `tbdcca.com`, the initial `wget` crawl skipped 51 project pages due to the strict `--domains=tbdcca.com` filter. Additionally, `wget --convert-links` prepended domain paths inside inline CSS `background-image` quotes on the downloaded project pages.

The [`pull_missing_pages.py`](./pull_missing_pages.py) script pulls pages based on the sitemap and fixes internal links.

```bash
# Dry run: view what would be downloaded or changed
python3 pull_missing_pages.py --dry-run
# Run full pull and link normalization
python3 pull_missing_pages.py
# Re-normalize links without re-downloading
python3 pull_missing_pages.py --skip-download
```

© 2026 California College of the Arts.
