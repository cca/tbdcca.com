#!/usr/bin/env python3
"""
pull_cdn_images.py

Static archival script for tbdcca.com CDN assets.

Background:
All website images (project galleries, thumbnails, branding, icons, banners)
are hosted on Webflow's CDN:
  https://cdn.prod.website-files.com/
along with site stylesheets and javascript scripts. Additionally, jQuery is
loaded from:
  https://d3e54v103j8qbb.cloudfront.net/

What this script does:
  1. Discovers all unique CDN image and asset URLs referenced across all HTML files
     (src, srcset, background-image in inline styles, icon hrefs, meta images)
     and in the site's shared Webflow CSS stylesheet.
  2. Uses `wget` with parallel worker processes to download all assets into their
     local host-based directory structure (e.g. `cdn.prod.website-files.com/...`).
  3. Rewrites all CDN URLs in HTML and CSS files to be fully relative:
     - Root HTML files -> `cdn.prod.website-files.com/...`
     - Project HTML files -> `../cdn.prod.website-files.com/...`
     - Shared CSS file -> relative paths `../...`
  4. Removes Subresource Integrity (`integrity="..."`) and `crossorigin="..."` attributes
     from all <link> and <script> tags so modified local stylesheets and scripts load
     without browser SRI mismatch rejections.
  5. Removes redundant CDN preconnect links from HTML headers.
  6. Supports `--dry-run`, `--force`, `--skip-download`, and `--concurrency`.
"""

import argparse
import concurrent.futures
import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = BASE_DIR / "project"
CDN_HOST = "cdn.prod.website-files.com"
CLOUDFRONT_HOST = "d3e54v103j8qbb.cloudfront.net"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Assets directly referenced in the Webflow CSS file
CSS_REFERENCED_ASSETS = [
    "https://cdn.prod.website-files.com/5a15fee745a0eb000185025c/5a16174f45a0eb0001850de4_FoundersGroteskMono-Demibold.woff2",
    "https://cdn.prod.website-files.com/5a15fee745a0eb000185025c/5a16174fca1ffe0001602eae_FoundersGroteskMono.woff2",
    "https://cdn.prod.website-files.com/5a15fee745a0eb000185025c/5a161954ca1ffe0001602fce_Knockout-HTF52-Cruiserweight.woff2",
    "https://cdn.prod.website-files.com/5a15fee745a0eb000185025c/5a161954cc80bd0001ecd999_Knockout-HTF29-JuniorLiteweight.woff2",
    "https://cdn.prod.website-files.com/5a15fee745a0eb000185025c/5a161954cc80bd0001ecd99a_Knockout-HTF74-FullSumo.woff2",
    "https://cdn.prod.website-files.com/5a15fee745a0eb000185025c/5a320fc44a2f7d000196f658_TBD_Symbol_Animated.gif",
    "https://cdn.prod.website-files.com/5a15fee745a0eb000185025c/5a4fdfa6b3d9e100018c79f4_Instagram.svg",
    "https://cdn.prod.website-files.com/5a15fee745a0eb000185025c/5a4fdfa6b462b2000143c19e_LinkedIn.svg",
    "https://cdn.prod.website-files.com/5a15fee745a0eb000185025c/5dfbdca294b5524dd8edb1e1_WebflowBanner_Galeria.gif",
]

JQUERY_URL = "https://d3e54v103j8qbb.cloudfront.net/js/jquery-3.5.1.min.dc5e7f18c8.js"
CLOUDFRONT_PLACEHOLDER = "https://d3e54v103j8qbb.cloudfront.net/img/background-image.svg"


def discover_cdn_urls():
    """
    Scans all HTML files in the repo and extracts all asset URLs from
    cdn.prod.website-files.com and d3e54v103j8qbb.cloudfront.net.
    Handles both original absolute URLs and already-rewritten local paths.
    """
    urls = set()
    html_files = sorted(list(BASE_DIR.glob("*.html")) + list(PROJECTS_DIR.glob("*.html")))

    for fpath in html_files:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as fp:
            text = html.unescape(fp.read())

        # Match absolute CDN URLs (handling filenames with parentheses/spaces)
        for m in re.finditer(r'https://cdn\.prod\.website-files\.com/[^\s"\'<>]+', text):
            u = m.group(0).rstrip(';,)"\'')
            if u != "https://cdn.prod.website-files.com":
                urls.add(u)

        # Match already-rewritten relative paths (e.g. cdn.prod.website-files.com/...)
        for m in re.finditer(r'(?:\.\./)?(cdn\.prod\.website-files\.com/[^\s"\'<>]+)', text):
            rel_u = m.group(1).rstrip(';,)"\'')
            urls.add(f"https://{rel_u}")

    urls.update(CSS_REFERENCED_ASSETS)
    return sorted(urls)


def get_expected_local_path(url):
    """
    Returns the expected local relative path on disk for a given URL.
    Handles unquoting percent-encoded characters as wget decodes them.
    """
    parsed = urlparse(url)
    rel_path = parsed.netloc + unquote(parsed.path)
    return BASE_DIR / rel_path


def download_batch_with_wget(urls_batch):
    """
    Runs a single wget process to download a batch of URLs.
    """
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
        batch_file = tf.name
        for u in urls_batch:
            tf.write(u + "\n")

    try:
        cmd = [
            "wget",
            "--no-verbose",
            "-x",
            "-P", str(BASE_DIR),
            "-U", USER_AGENT,
            "-i", batch_file,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.returncode == 0, res.stderr
    finally:
        if os.path.exists(batch_file):
            os.remove(batch_file)


def download_all_assets(urls, concurrency=8, dry_run=False, force=False):
    """
    Downloads all discovered CDN assets using parallel wget processes.
    """
    to_download = []
    for u in urls:
        local_path = get_expected_local_path(u)
        if force or not local_path.exists():
            to_download.append(u)

    print(f"Total CDN assets identified: {len(urls)}")
    print(f"Assets already on disk: {len(urls) - len(to_download)}")
    print(f"Assets to download: {len(to_download)}")

    if not to_download:
        print("All assets already downloaded.")
        return True

    if dry_run:
        print(f"[DRY-RUN] Would download {len(to_download)} files with {concurrency} parallel wget workers.")
        return True

    # Also download Cloudfront jQuery and background-image.svg
    for extra_url in [JQUERY_URL, CLOUDFRONT_PLACEHOLDER]:
        extra_path = get_expected_local_path(extra_url)
        if force or not extra_path.exists():
            extra_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([
                "wget", "--no-verbose",
                "-U", USER_AGENT,
                "-O", str(extra_path),
                extra_url,
            ], capture_output=True)

    # Shard into batches for parallel wget workers
    batch_size = (len(to_download) + concurrency - 1) // concurrency
    batches = [to_download[i:i + batch_size] for i in range(0, len(to_download), batch_size)]

    print(f"Starting parallel download with {len(batches)} workers ({batch_size} URLs/batch)...")
    success = True

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(batches)) as executor:
        futures = {executor.submit(download_batch_with_wget, batch): idx for idx, batch in enumerate(batches)}
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            ok, err = future.result()
            completed += 1
            if not ok:
                success = False
                print(f"  Worker batch failed: {err.strip()[:100]}", file=sys.stderr)
            else:
                print(f"  Worker batch {completed}/{len(batches)} completed.")

    return success


def rewrite_html_files(dry_run=False):
    """
    Rewrites CDN URLs in all HTML files to relative local paths,
    removes Subresource Integrity (`integrity="..."`) and `crossorigin="..."`
    attributes, and cleans up redundant CDN preconnect tags.
    """
    html_files = sorted(list(BASE_DIR.glob("*.html")) + list(PROJECTS_DIR.glob("*.html")))
    total_files_updated = 0
    total_urls_replaced = 0
    total_integrity_removed = 0

    for fpath in html_files:
        is_project_dir = fpath.parent.name == "project"
        prefix = "../" if is_project_dir else ""

        with open(fpath, "r", encoding="utf-8", errors="ignore") as fp:
            content = fp.read()

        updated = content
        count = 0

        # 1. Replace https://cdn.prod.website-files.com/ with prefix + cdn.prod.website-files.com/
        cdn_pattern = r'https://cdn\.prod\.website-files\.com/'
        matches = len(re.findall(cdn_pattern, updated))
        if matches > 0:
            count += matches
            updated = re.sub(cdn_pattern, f'{prefix}{CDN_HOST}/', updated)

        # 2. Replace Cloudfront jQuery script
        cf_pattern = r'https://d3e54v103j8qbb\.cloudfront\.net/js/jquery-3\.5\.1\.min\.dc5e7f18c8\.js(?:\?site=[a-zA-Z0-9]+)?'
        cf_matches = len(re.findall(cf_pattern, updated))
        if cf_matches > 0:
            count += cf_matches
            updated = re.sub(cf_pattern, f'{prefix}{CLOUDFRONT_HOST}/js/jquery-3.5.1.min.dc5e7f18c8.js', updated)

        # 3. Remove Subresource Integrity (integrity="...") attributes
        integrity_count = len(re.findall(r'\s+integrity="[^"]*"', updated))
        if integrity_count > 0:
            total_integrity_removed += integrity_count
            updated = re.sub(r'\s+integrity="[^"]*"', '', updated)

        # 4. Remove crossorigin="..." attributes
        crossorigin_count = len(re.findall(r'\s+crossorigin="[^"]*"', updated))
        if crossorigin_count > 0:
            updated = re.sub(r'\s+crossorigin="[^"]*"', '', updated)

        # 5. Remove redundant CDN preconnect tag
        preconnect_pattern = r'<link\s+href="https://cdn\.prod\.website-files\.com"\s+rel="preconnect"\s+crossorigin="anonymous"/>'
        if re.search(preconnect_pattern, updated):
            updated = re.sub(preconnect_pattern, '', updated)

        if count > 0 or updated != content:
            total_files_updated += 1
            total_urls_replaced += count
            if not dry_run:
                with open(fpath, "w", encoding="utf-8") as fp:
                    fp.write(updated)
            rel_name = fpath.relative_to(BASE_DIR).as_posix()
            note_parts = []
            if count > 0:
                note_parts.append(f"{count} CDN URLs rewritten")
            if integrity_count > 0:
                note_parts.append(f"{integrity_count} integrity attributes removed")
            note_str = " (" + ", ".join(note_parts) + ")" if note_parts else ""
            print(f"  Updated {rel_name}{note_str}")

    return total_files_updated, total_urls_replaced, total_integrity_removed


def rewrite_css_files(dry_run=False):
    """
    Rewrites absolute CDN URLs inside downloaded CSS files to be relative.
    """
    css_file = BASE_DIR / CDN_HOST / "5a15fee745a0eb000185025c" / "css" / "tbdcca.webflow.shared.6c3651ba2.min.css"
    if not css_file.exists():
        return 0

    with open(css_file, "r", encoding="utf-8", errors="ignore") as fp:
        content = fp.read()

    # In css/tbdcca.webflow.shared...min.css:
    # 1. 5a15fee745a0eb000185025c assets -> ../
    target_str = "https://cdn.prod.website-files.com/5a15fee745a0eb000185025c/"
    count = content.count(target_str)
    updated = content.replace(target_str, "../")

    # 2. Cloudfront background-image.svg -> ../../../d3e54v103j8qbb.cloudfront.net/img/background-image.svg
    cf_target = "https://d3e54v103j8qbb.cloudfront.net/img/background-image.svg"
    cf_count = updated.count(cf_target)
    if cf_count > 0:
        count += cf_count
        updated = updated.replace(cf_target, "../../../d3e54v103j8qbb.cloudfront.net/img/background-image.svg")

    if count > 0:
        if not dry_run:
            with open(css_file, "w", encoding="utf-8") as fp:
                fp.write(updated)
        print(f"  Updated {css_file.relative_to(BASE_DIR).as_posix()}: {count} internal URLs rewritten to relative")

    return count


def main():
    parser = argparse.ArgumentParser(description="Pull CDN images and assets and rewrite references to be relative.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without modifying files or downloading.")
    parser.add_argument("--force", action="store_true", help="Re-download assets even if they already exist locally.")
    parser.add_argument("--skip-download", action="store_true", help="Skip downloading, only rewrite URLs and remove integrity.")
    parser.add_argument("--concurrency", type=int, default=8, help="Number of parallel wget workers (default: 8).")
    args = parser.parse_args()

    print("=== Step 1: Discovering CDN asset URLs ===")
    cdn_urls = discover_cdn_urls()
    print(f"Discovered {len(cdn_urls)} unique CDN asset URLs.")

    if not args.skip_download:
        print(f"\n=== Step 2: Downloading assets via wget (concurrency={args.concurrency}) ===")
        ok = download_all_assets(cdn_urls, concurrency=args.concurrency, dry_run=args.dry_run, force=args.force)
        if not ok:
            print("Warning: Some assets may have encountered download errors.", file=sys.stderr)
    else:
        print("\n=== Step 2: Skipping download (--skip-download specified) ===")

    print("\n=== Step 3: Rewriting URLs and stripping integrity attributes across HTML and CSS ===")
    html_mod, html_urls, integrity_count = rewrite_html_files(dry_run=args.dry_run)
    css_urls = rewrite_css_files(dry_run=args.dry_run)

    print("\n=== Summary ===")
    print(f"Total CDN assets: {len(cdn_urls)}")
    print(f"HTML files updated: {html_mod}")
    print(f"HTML CDN URLs rewritten to relative: {html_urls}")
    print(f"Subresource Integrity attributes removed: {integrity_count}")
    print(f"CSS asset URLs rewritten to relative: {css_urls}")
    print("\nDone! All CDN assets pulled, references converted to relative paths, and integrity attributes removed.")


if __name__ == "__main__":
    main()
