#!/usr/bin/env python3
"""Generate ``src/map_tiles_downloader/data/admin1_names.json``.

This script builds a mapping of GeoNames admin1 codes (``CC.CODE``, e.g.
``"PL.78"`` or ``"US.CA"``) to human-readable region names in the region's
local/official language (e.g. ``"Mazowieckie"`` or ``"California"``).

Three data sources are combined (highest priority first):

1. **pycountry** (ISO 3166-2) — provides local-language names for countries
   whose GeoNames admin1 codes match their ISO 3166-2 subdivision codes
   (e.g. US.CA → US-CA → "California", GB.ENG → GB-ENG → "England").
2. **geonamescache** ``get_us_states()`` — authoritative US state names
   already bundled with the package.
3. **GeoNames ``admin1CodesASCII.txt``** (downloaded) — English/transliterated
   names for every admin1 region in the world, filling in any gaps left by
   the two local-name sources above.

Usage
-----
Install the required extra dependency, then run this script from the repo
root.  It writes the JSON file in place so it is ready to commit::

    pip install pycountry
    python scripts/generate_admin1_names.py

If you want to preview the output without touching the repository file, use
``--stdout``::

    python scripts/generate_admin1_names.py --stdout

To use a locally downloaded copy of ``admin1CodesASCII.txt`` instead of
fetching it from geonames.org (useful in air-gapped environments)::

    python scripts/generate_admin1_names.py --geonames-file /path/to/admin1CodesASCII.txt
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Default output path — relative to this script's location
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_OUTPUT = _REPO_ROOT / "src" / "map_tiles_downloader" / "data" / "admin1_names.json"

_GEONAMES_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_package(name: str) -> None:
    try:
        __import__(name)
    except ImportError:
        print(
            f"ERROR: Required package '{name}' is not installed.\n"
            f"  Install it with:  pip install {name}",
            file=sys.stderr,
        )
        sys.exit(1)


def _strip_pycountry_annotation(name: str) -> str:
    """Remove the bracketed annotation that pycountry sometimes appends.

    E.g. ``"Wales [Cymru GB-CYM]"`` → ``"Wales"``.
    """
    if " [" in name:
        return name[: name.index(" [")]
    return name


# ---------------------------------------------------------------------------
# Source 1: pycountry local-language names for letter-code countries
# ---------------------------------------------------------------------------


def _names_from_pycountry_letter_codes() -> dict[str, str]:
    """Return names for countries that use letter-based GeoNames admin1 codes.

    For these countries the GeoNames ``CC.CODE`` directly maps to the ISO
    3166-2 subdivision code ``CC-CODE``, so pycountry gives us the
    local/official name without any extra mapping.
    """
    import geonamescache  # noqa: PLC0415
    import pycountry  # noqa: PLC0415

    gc = geonamescache.GeonamesCache()

    # Collect every admin1 code seen in the cities dataset
    admin1_per_cc: dict[str, set[str]] = {}
    for city in gc.get_cities().values():
        cc = city.get("countrycode")
        a1 = city.get("admin1code")
        if cc and a1:
            admin1_per_cc.setdefault(cc, set()).add(a1)

    names: dict[str, str] = {}
    for cc, codes in admin1_per_cc.items():
        for code in codes:
            if code.isdigit():
                continue  # skip numeric codes — unreliable pycountry match
            pysub = pycountry.subdivisions.get(code=f"{cc}-{code}")
            if pysub:
                names[f"{cc}.{code}"] = _strip_pycountry_annotation(pysub.name)
    return names


# ---------------------------------------------------------------------------
# Source 2: geonamescache US state names (already bundled, authoritative)
# ---------------------------------------------------------------------------


def _names_from_us_states() -> dict[str, str]:
    import geonamescache  # noqa: PLC0415

    gc = geonamescache.GeonamesCache()
    return {f"US.{code}": info["name"] for code, info in gc.get_us_states().items()}


# ---------------------------------------------------------------------------
# Source 3: GeoNames admin1CodesASCII.txt
# ---------------------------------------------------------------------------


def _parse_admin1_codes_file(text: str) -> dict[str, str]:
    """Parse the tab-separated admin1CodesASCII.txt content.

    Each line has four tab-separated fields::

        CC.CODE <TAB> Name <TAB> ASCIIName <TAB> GeonamesId

    The *Name* field (column 1) is preferred over the ASCII version because
    it preserves diacritics and local characters where present.
    """
    names: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] and parts[1]:
            names[parts[0]] = parts[1]
    return names


def _download_geonames_admin1() -> dict[str, str] | None:
    """Download admin1CodesASCII.txt from geonames.org and parse it."""
    print(f"Downloading {_GEONAMES_URL} …", file=sys.stderr)
    try:
        req = urllib.request.Request(
            _GEONAMES_URL,
            headers={"User-Agent": "map-tiles-downloader/generate_admin1_names"},
        )
        # S310: URL is a module-level constant pointing to the official GeoNames
        # server; using the requests library is not worth adding as a dependency
        # for a developer-only script.
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            content = resp.read().decode("utf-8")
        names = _parse_admin1_codes_file(content)
        print(f"  Downloaded {len(names):,} entries.", file=sys.stderr)
        return names
    except Exception as exc:
        print(f"  Download failed: {exc}", file=sys.stderr)
        return None


def _load_geonames_admin1_file(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8") as fh:
        return _parse_admin1_codes_file(fh.read())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_names(geonames_file: str | None = None) -> dict[str, str]:
    """Build the complete admin1 names mapping."""
    _require_package("geonamescache")
    _require_package("pycountry")

    print("Building from pycountry (letter-code countries) …", file=sys.stderr)
    names = _names_from_pycountry_letter_codes()
    print(f"  {len(names):,} entries", file=sys.stderr)

    print("Adding US state names from geonamescache …", file=sys.stderr)
    us = _names_from_us_states()
    names.update(us)  # US names from geonamescache take precedence over pycountry
    print(f"  {len(us)} US entries merged", file=sys.stderr)

    # GeoNames data fills in the remaining countries (with English names)
    if geonames_file:
        print(f"Loading GeoNames data from {geonames_file} …", file=sys.stderr)
        gn = _load_geonames_admin1_file(geonames_file)
    else:
        gn = _download_geonames_admin1()

    if gn:
        before = len(names)
        for key, name in gn.items():
            # Only fill in entries not already covered by the local-language sources
            if key not in names:
                names[key] = name
        added = len(names) - before
        print(f"  {added:,} new entries added from GeoNames", file=sys.stderr)
    else:
        print(
            "  WARNING: GeoNames data unavailable — only partial data will be written.\n"
            "           Countries with numeric GeoNames admin1 codes (e.g. DE, PL, FR)\n"
            "           will still show raw codes instead of region names.\n"
            "           Re-run this script with internet access to get full coverage.",
            file=sys.stderr,
        )

    print(f"Total: {len(names):,} admin1 entries", file=sys.stderr)
    return names


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--geonames-file",
        metavar="PATH",
        help="Path to a local admin1CodesASCII.txt instead of downloading it.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=str(_DEFAULT_OUTPUT),
        help=f"Output JSON file (default: {_DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print JSON to stdout instead of writing to --output.",
    )
    args = parser.parse_args()

    names = build_names(geonames_file=args.geonames_file)
    serialized = json.dumps(names, ensure_ascii=False, sort_keys=True, indent=2)

    if args.stdout:
        print(serialized)
    else:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(serialized + "\n", encoding="utf-8")
        print(f"Written to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
