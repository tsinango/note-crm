#!/usr/bin/env python3
"""Download all Bootswatch Bootstrap 5 themes to static/vendor/bootswatch/."""
import json
import os
import sys
import urllib.request
import urllib.error

API_URL = "https://bootswatch.com/api/5.json"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "vendor", "bootswatch")

# Fallback theme list if API fails
FALLBACK_THEMES = [
    "brite", "cerulean", "cosmo", "cyborg", "darkly", "flatly",
    "journal", "litera", "lumen", "lux", "materia", "minty",
    "morph", "pulse", "quartz", "sandstone", "simplex", "sketchy",
    "slate", "solar", "spacelab", "superhero", "united", "vapor",
    "yeti", "zephyr",
]


def fetch_api():
    """Fetch Bootswatch API JSON. Returns (themes_dict, error)."""
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "note-crm/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            themes = data.get("themes", [])
            return [
                {
                    "name": t["name"].lower(),
                    "displayName": t["name"],
                    "description": t.get("description", ""),
                    "css": t.get("cssCdn", ""),
                    "preview": t.get("preview", ""),
                }
                for t in themes
            ], None
    except Exception as e:
        return None, str(e)


def download_css(url, filepath):
    """Download a CSS file. Returns True on success."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "note-crm/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print("Fetching Bootswatch API...")
    themes, err = fetch_api()

    if err or not themes:
        print(f"API fetch failed ({err or 'no themes'}), using fallback list.")
        themes = [
            {"name": t, "displayName": t.capitalize(), "description": "", "css": "", "preview": ""}
            for t in FALLBACK_THEMES
        ]

    downloaded = []
    for t in themes:
        name = t["name"]
        css_url = t.get("css", "")
        if not css_url:
            css_url = f"https://bootswatch.com/5/{name}/bootstrap.min.css"

        filepath = os.path.join(OUT_DIR, name, "bootstrap.min.css")
        print(f"  {name} ... ", end="", flush=True)
        if download_css(css_url, filepath):
            print("OK")
            downloaded.append(t)
        else:
            print(f"FAILED (tried {css_url})")

    # Save theme manifest
    manifest_path = os.path.join(OUT_DIR, "themes.json")
    manifest = [
        {
            "name": t["name"],
            "displayName": t["displayName"],
            "description": t.get("description", ""),
            "preview": t.get("preview", ""),
        }
        for t in downloaded
    ]
    with open(manifest_path, "w") as f:
        json.dump({"themes": manifest}, f, indent=2)

    print(f"\nSaved theme manifest: {manifest_path}")
    print(f"Downloaded {len(downloaded)}/{len(themes)} themes.")


if __name__ == "__main__":
    main()
