#!/usr/bin/env python3
"""
pull_missing_pages.py

Static archival script for tbdcca.com.

Background:
The initial wget mirror of tbdcca.com used:
  wget --mirror --convert-links --adjust-extension --page-requisites --no-parent \\
       --output-file=tbdcca.com.log --domains=tbdcca.com https://tbdcca.com

Because many gallery and project links in index.html and project.html used absolute
URLs pointing to www.tbdcca.com (or http://www.tbdcca.com), wget's domain filter
(--domains=tbdcca.com) skipped them. As a result:
  - 51 project pages were never downloaded.
  - Links to those 51 project pages remained absolute URLs to www.tbdcca.com.
  - wget's --convert-links corrupted inline CSS background-image URLs in the 22
    downloaded project files (prepending http://tbdcca.com/project/&quot;https:).

What this script does:
  1. Parses sitemap.xml (or crawls the site) to identify all pages.
  2. Uses `wget` to fetch any missing HTML pages (e.g. 51 missing projects, search.html, robots.txt).
  3. Updates all absolute internal links (to tbdcca.com / www.tbdcca.com) and root-relative
     paths across all HTML files in the repo to be relative paths.
  4. Fixes the corrupted inline CSS background-image URLs in existing project files.
"""

import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = BASE_DIR / "project"
SITEMAP_FILE = BASE_DIR / "sitemap.xml"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def get_all_target_pages():
    """
    Returns a dict mapping local relative path to remote URL.
    Example:
      'project/2h-gallery.html': 'https://tbdcca.com/project/2h-gallery',
      'search.html': 'https://tbdcca.com/search',
      'robots.txt': 'https://tbdcca.com/robots.txt'
    """
    targets = {}

    if SITEMAP_FILE.exists():
        try:
            tree = ET.parse(SITEMAP_FILE)
            for loc in tree.findall(
                ".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"
            ):
                url = loc.text.strip() if loc.text else ""
                if not url:
                    continue
                u = urlparse(url)
                path = u.path.strip("/")
                if not path:
                    targets["index.html"] = url
                elif path == "about":
                    targets["about.html"] = url
                elif path == "project":
                    targets["project.html"] = url
                elif path == "search":
                    targets["search.html"] = url
                elif path.startswith("project/"):
                    slug = path.split("project/")[-1]
                    targets[f"project/{slug}.html"] = url
        except Exception as e:  # noqa: BLE001
            print(f"Warning: Failed to parse {SITEMAP_FILE}: {e}")

    # Fallback/supplement: scan HTML links in index.html and project.html
    for scan_file in [BASE_DIR / "index.html", BASE_DIR / "project.html"]:
        if not scan_file.exists():
            continue
        with open(scan_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        for m in re.finditer(
            r'href=["\'](https?://(?:www\.)?tbdcca\.com/project/([a-zA-Z0-9_-]+))/?["\']',
            content,
        ):
            full_url, slug = m.group(1), m.group(2)
            rel_path = f"project/{slug}.html"
            if rel_path not in targets:
                targets[rel_path] = f"https://tbdcca.com/project/{slug}"

    if "robots.txt" not in targets:
        targets["robots.txt"] = "https://tbdcca.com/robots.txt"

    return targets


def download_page_with_wget(url, dest_path, dry_run=False):
    """
    Uses wget to fetch the page and save it directly to dest_path.
    """
    if dry_run:
        print(f"[DRY-RUN] wget -U '{USER_AGENT}' -O '{dest_path}' '{url}'")
        return True

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "wget",
        "--no-verbose",
        "-U",
        USER_AGENT,
        "-O",
        str(dest_path),
        url,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    if res.returncode != 0:
        print(f"Error fetching {url}: {res.stderr.strip()}", file=sys.stderr)
        return False
    return True


def convert_link(href, current_file_rel):
    """
    Converts internal absolute and root-relative URLs into relative links
    relative to current_file_rel (e.g. 'index.html' or 'project/act.html').
    Leaves external URLs and same-page anchor links untouched.
    """
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return href

    u = urlparse(href)

    # Internal if domain matches tbdcca.com or www.tbdcca.com, or root-relative path
    is_internal = False
    if u.netloc in ("tbdcca.com", "www.tbdcca.com") or (
        not u.netloc and (u.path.startswith("/") or "project/" in u.path)
    ):
        is_internal = True

    if not is_internal:
        return href

    path = u.path
    is_in_project_dir = current_file_rel.startswith("project/")

    # Match /project/<slug> or project/<slug> or <slug>.html
    m_proj = re.match(r"^/?project/([a-zA-Z0-9_-]+)(?:\.html)?/?$", path)
    if m_proj:
        slug = m_proj.group(1)
        target = f"{slug}.html" if is_in_project_dir else f"project/{slug}.html"
    elif path in ("/project", "/project/", "project", "project/"):
        target = "../project.html" if is_in_project_dir else "project.html"
    elif path in ("/about", "/about/", "about", "about/"):
        target = "../about.html" if is_in_project_dir else "about.html"
    elif path in ("/search", "/search/", "search", "search/"):
        target = "../search.html" if is_in_project_dir else "search.html"
    elif path in ("/", ""):
        target = "../index.html" if is_in_project_dir else "index.html"
    else:
        target = path

    if u.fragment:
        target += f"#{u.fragment}"

    return target


def update_file_links(file_path, dry_run=False):
    """
    Scans file_path for internal links (href, action) and converts them to relative links.
    Also repairs corrupted inline CSS background-image URLs.
    Returns (num_links_changed, had_css_fix).
    """
    rel_path = file_path.relative_to(BASE_DIR).as_posix()
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    changes = 0

    def replace_attr(m):
        nonlocal changes
        attr = m.group(1)
        val = m.group(2)
        new_val = convert_link(val, rel_path)
        if new_val != val:
            changes += 1
            return f'{attr}="{new_val}"'
        return m.group(0)

    # Match href="..." and action="..."
    updated_content = re.sub(r'\b(href|action)="([^"]*)"', replace_attr, content)

    # Fix inline CSS background-image url corruption caused by wget's --convert-links
    css_fixed = False
    for bad_prefix in [
        "url(http://tbdcca.com/project/&quot;https:",
        "url(https://tbdcca.com/project/&quot;https:",
        "url(http://www.tbdcca.com/project/&quot;https:",
        "url(https://www.tbdcca.com/project/&quot;https:",
    ]:
        if bad_prefix in updated_content:
            updated_content = updated_content.replace(bad_prefix, "url(&quot;https:")
            css_fixed = True

    if (changes > 0 or css_fixed) and not dry_run:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

    return changes, css_fixed


def main():
    parser = argparse.ArgumentParser(
        description="Pull missing pages via wget and update links to be relative."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate without modifying files or downloading.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download pages even if they already exist locally.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip downloading, only update relative links.",
    )
    args = parser.parse_args()

    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Step 1: Identifying target pages ===")
    targets = get_all_target_pages()
    print(f"Found {len(targets)} total pages defined in sitemap/site.")

    if not args.skip_download:
        print("\n=== Step 2: Downloading missing pages via wget ===")
        to_download = {}
        for rel_path, url in targets.items():
            dest = BASE_DIR / rel_path
            if args.force or not dest.exists():
                to_download[rel_path] = (url, dest)

        print(f"Pages to download: {len(to_download)}")
        success_count = 0
        for i, (rel_path, (url, dest)) in enumerate(to_download.items(), 1):
            print(f"[{i}/{len(to_download)}] Downloading {rel_path} from {url}...")
            ok = download_page_with_wget(url, dest, dry_run=args.dry_run)
            if ok:
                success_count += 1

        print(f"Successfully downloaded {success_count}/{len(to_download)} pages.")
    else:
        print("\n=== Step 2: Skipping download (--skip-download specified) ===")

    print("\n=== Step 3: Updating links to be relative across all HTML files ===")
    html_files = sorted(
        list(BASE_DIR.glob("*.html")) + list(PROJECTS_DIR.glob("*.html"))
    )
    total_files_modified = 0
    total_links_changed = 0
    total_css_fixed = 0

    for f in html_files:
        changes, css_fixed = update_file_links(f, dry_run=args.dry_run)
        if changes > 0 or css_fixed:
            total_files_modified += 1
            total_links_changed += changes
            if css_fixed:
                total_css_fixed += 1
            rel_name = f.relative_to(BASE_DIR).as_posix()
            css_note = " (+ repaired banner style)" if css_fixed else ""
            print(f"  Updated {rel_name}: {changes} links converted{css_note}")

    print("\n=== Summary ===")
    print(f"Total HTML files in repository: {len(html_files)}")
    print(f"Files modified: {total_files_modified}")
    print(f"Links converted to relative: {total_links_changed}")
    print(f"Banner image inline styles repaired: {total_css_fixed}")
    print("\nDone! All pages pulled and internal links normalized.")


if __name__ == "__main__":
    main()
