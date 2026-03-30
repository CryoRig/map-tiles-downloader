import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from map_tiles_downloader.regions import _parse_country_bbox, _load_admin1_names, load_region_catalog


class TestParseCountryBbox:
    def test_parse_country_bbox_natural_earth_style(self):
        country = {"bbox": {"west": -10.0, "south": 35.0, "east": 5.0, "north": 45.0}}
        result = _parse_country_bbox(country)
        assert result == (35.0, -10.0, 45.0, 5.0)  # south, west, north, east

    def test_parse_country_bbox_min_max_style(self):
        country = {"bbox": {"min": {"lat": 35.0, "lon": -10.0}, "max": {"lat": 45.0, "lon": 5.0}}}
        result = _parse_country_bbox(country)
        assert result == (35.0, -10.0, 45.0, 5.0)

    def test_parse_country_bbox_missing_bbox(self):
        country = {}
        result = _parse_country_bbox(country)
        assert result is None

    def test_parse_country_bbox_missing_keys(self):
        country = {"bbox": {"west": -10.0}}  # Missing other keys
        result = _parse_country_bbox(country)
        assert result is None

    def test_parse_country_bbox_invalid_data(self):
        country = {"bbox": {"west": "invalid", "south": 35.0, "east": 5.0, "north": 45.0}}
        result = _parse_country_bbox(country)
        assert result is None


class TestLoadAdmin1Names:
    def test_returns_empty_dict_when_file_missing(self, tmp_path):
        import map_tiles_downloader.regions as regions_mod

        original = regions_mod._ADMIN1_NAMES_FILE
        try:
            regions_mod._ADMIN1_NAMES_FILE = tmp_path / "nonexistent.json"
            result = _load_admin1_names()
            assert result == {}
        finally:
            regions_mod._ADMIN1_NAMES_FILE = original

    def test_loads_valid_json_file(self, tmp_path):
        import map_tiles_downloader.regions as regions_mod

        data = {"US.CA": "California", "PL.78": "Mazowieckie"}
        json_file = tmp_path / "admin1_names.json"
        json_file.write_text(json.dumps(data), encoding="utf-8")

        original = regions_mod._ADMIN1_NAMES_FILE
        try:
            regions_mod._ADMIN1_NAMES_FILE = json_file
            result = _load_admin1_names()
            assert result == {"US.CA": "California", "PL.78": "Mazowieckie"}
        finally:
            regions_mod._ADMIN1_NAMES_FILE = original

    def test_returns_empty_dict_on_corrupt_json(self, tmp_path):
        import map_tiles_downloader.regions as regions_mod

        json_file = tmp_path / "admin1_names.json"
        json_file.write_text("NOT VALID JSON {{{", encoding="utf-8")

        original = regions_mod._ADMIN1_NAMES_FILE
        try:
            regions_mod._ADMIN1_NAMES_FILE = json_file
            result = _load_admin1_names()
            assert result == {}
        finally:
            regions_mod._ADMIN1_NAMES_FILE = original

    def test_returns_empty_dict_when_content_is_not_a_dict(self, tmp_path):
        import map_tiles_downloader.regions as regions_mod

        json_file = tmp_path / "admin1_names.json"
        json_file.write_text(json.dumps(["list", "not", "dict"]), encoding="utf-8")

        original = regions_mod._ADMIN1_NAMES_FILE
        try:
            regions_mod._ADMIN1_NAMES_FILE = json_file
            result = _load_admin1_names()
            assert result == {}
        finally:
            regions_mod._ADMIN1_NAMES_FILE = original


class TestLoadRegionCatalog:
    @patch("map_tiles_downloader.regions.geonamescache")
    def test_load_region_catalog_basic_structure(self, mock_geonamescache):
        # Mock geonamescache data
        mock_gc = MagicMock()
        mock_geonamescache.GeonamesCache.return_value = mock_gc

        # Mock continents
        mock_gc.get_continents.return_value = {
            "EU": {"name": "Europe"},
            "NA": {"name": "North America"},
        }

        # Mock countries (should be dict with country codes as keys)
        mock_gc.get_countries.return_value = {
            "FR": {
                "continentcode": "EU",
                "name": "France",
                "iso": "FR",
                "bbox": {"west": -5.0, "south": 41.0, "east": 10.0, "north": 51.0},
            },
            "US": {
                "continentcode": "NA",
                "name": "United States",
                "iso": "US",
                "bbox": {"west": -125.0, "south": 25.0, "east": -65.0, "north": 50.0},
            },
        }

        # Mock subdivisions (newer geonamescache versions)
        mock_gc.get_subdivisions.return_value = {
            "US.CA": {"name": "California"},
            "US.NY": {"name": "New York"},
        }

        # Mock cities for admin1 bbox calculation
        mock_gc.get_cities.return_value = {
            "1": {
                "countrycode": "US",
                "admin1code": "CA",
                "latitude": "36.7783",
                "longitude": "-119.4179",
            },
            "2": {
                "countrycode": "US",
                "admin1code": "NY",
                "latitude": "40.7128",
                "longitude": "-74.0060",
            },
        }

        catalog = load_region_catalog()

        # Check structure
        assert isinstance(catalog, dict)
        assert "Europe" in catalog
        assert "North America" in catalog

        # Check countries exist
        assert "France" in catalog["Europe"]
        assert "United States" in catalog["North America"]

    @patch("map_tiles_downloader.regions.geonamescache")
    def test_load_region_catalog_handles_missing_subdivisions(self, mock_geonamescache):
        # Test fallback when subdivisions getter is not available (older geonamescache)
        mock_gc = MagicMock()
        mock_geonamescache.GeonamesCache.return_value = mock_gc

        # Mock continents
        mock_gc.get_continents.return_value = {"EU": {"name": "Europe"}}

        # Mock countries
        mock_gc.get_countries.return_value = {
            "FR": {
                "continentcode": "EU",
                "name": "France",
                "iso": "FR",
                "bbox": {"west": -5.0, "south": 41.0, "east": 10.0, "north": 51.0},
            }
        }

        # Mock subdivisions getter as None (older versions)
        mock_gc.get_subdivisions = None

        # Mock cities
        mock_gc.get_cities.return_value = {}

        catalog = load_region_catalog()

        # Should still work without subdivisions
        assert "Europe" in catalog
        assert "France" in catalog["Europe"]

    @patch("map_tiles_downloader.regions.geonamescache")
    def test_load_region_catalog_handles_exceptions(self, mock_geonamescache):
        # Test that exceptions in processing don't break the whole catalog
        mock_gc = MagicMock()
        mock_geonamescache.GeonamesCache.return_value = mock_gc

        mock_gc.get_continents.return_value = {"EU": {"name": "Europe"}}

        # One good country, one that will cause an exception
        mock_gc.get_countries.return_value = {
            "FR": {
                "continentcode": "EU",
                "name": "France",
                "iso": "FR",
                "bbox": {"west": -5.0, "south": 41.0, "east": 10.0, "north": 51.0},
            },
            "BAD": {
                "continentcode": "EU",
                "name": None,  # This will cause issues
                "iso": None,
                "bbox": None,
            },
        }

        mock_gc.get_subdivisions.return_value = {}
        mock_gc.get_cities.return_value = {}

        catalog = load_region_catalog()

        # Should still have France despite the problematic country
        assert "Europe" in catalog
        assert "France" in catalog["Europe"]

    @patch("map_tiles_downloader.regions.geonamescache")
    def test_load_region_catalog_city_bbox_aggregation(self, mock_geonamescache):
        # Test the city-based bbox aggregation for admin1 regions
        mock_gc = MagicMock()
        mock_geonamescache.GeonamesCache.return_value = mock_gc

        mock_gc.get_continents.return_value = {"NA": {"name": "North America"}}

        mock_gc.get_countries.return_value = {
            "US": {"continentcode": "NA", "name": "United States", "iso": "US"}
        }

        mock_gc.get_subdivisions.return_value = {
            "US.CA": {"name": "California"},
            "US.TX": {"name": "Texas"},
        }

        # Cities for California and Texas
        mock_gc.get_cities.return_value = {
            "1": {
                "countrycode": "US",
                "admin1code": "CA",
                "latitude": "36.0",
                "longitude": "-120.0",
            },
            "2": {
                "countrycode": "US",
                "admin1code": "CA",
                "latitude": "38.0",
                "longitude": "-118.0",
            },
            "3": {
                "countrycode": "US",
                "admin1code": "TX",
                "latitude": "31.0",
                "longitude": "-100.0",
            },
            "4": {
                "countrycode": "US",
                "admin1code": "TX",
                "latitude": "33.0",
                "longitude": "-98.0",
            },
        }

        catalog = load_region_catalog()

        assert "North America" in catalog
        assert "United States" in catalog["North America"]

        us_states = catalog["North America"]["United States"]

        # Should have California and Texas with aggregated bboxes
        assert "California" in us_states
        assert "Texas" in us_states

        # Check California bbox (south: 36.0, west: -120.0, north: 38.0, east: -118.0)
        ca_bbox = us_states["California"]
        assert ca_bbox[0] == 36.0  # south
        assert ca_bbox[1] == -120.0  # west
        assert ca_bbox[2] == 38.0  # north
        assert ca_bbox[3] == -118.0  # east

    @patch("map_tiles_downloader.regions.geonamescache")
    def test_load_region_catalog_fallback_country_bbox(self, mock_geonamescache):
        # Test fallback to country-wide bbox when no states are computed
        mock_gc = MagicMock()
        mock_geonamescache.GeonamesCache.return_value = mock_gc

        mock_gc.get_continents.return_value = {"EU": {"name": "Europe"}}

        mock_gc.get_countries.return_value = {
            "MC": {
                "continentcode": "EU",
                "name": "Monaco",
                "iso": "MC",
                "bbox": {"west": 7.4, "south": 43.7, "east": 7.4, "north": 43.8},
            }
        }

        mock_gc.get_subdivisions.return_value = {}
        mock_gc.get_cities.return_value = {}  # No cities for Monaco

        catalog = load_region_catalog()

        assert "Europe" in catalog
        assert "Monaco" in catalog["Europe"]

        monaco_states = catalog["Europe"]["Monaco"]
        # Should have "All of Monaco" as fallback
        assert "All of Monaco" in monaco_states
        assert monaco_states["All of Monaco"] == (43.7, 7.4, 43.8, 7.4)

    @patch("map_tiles_downloader.regions._load_admin1_names")
    @patch("map_tiles_downloader.regions.geonamescache")
    def test_admin1_names_used_for_region_display(self, mock_geonamescache, mock_load_names):
        """Bundled admin1_names.json provides proper names instead of raw codes."""
        mock_gc = MagicMock()
        mock_geonamescache.GeonamesCache.return_value = mock_gc

        mock_gc.get_continents.return_value = {"EU": {"name": "Europe"}}
        mock_gc.get_countries.return_value = {
            "PL": {
                "continentcode": "EU",
                "name": "Poland",
                "iso": "PL",
                "bbox": {"west": 14.0, "south": 49.0, "east": 24.0, "north": 55.0},
            }
        }
        mock_gc.get_subdivisions = None  # simulate older geonamescache without this method

        # Cities that produce two Polish admin1 bboxes (codes "72" and "78")
        mock_gc.get_cities.return_value = {
            "1": {"countrycode": "PL", "admin1code": "72", "latitude": "51.1", "longitude": "17.0"},
            "2": {"countrycode": "PL", "admin1code": "78", "latitude": "52.2", "longitude": "21.0"},
        }

        # Provide admin1 names as if loaded from admin1_names.json
        mock_load_names.return_value = {
            "PL.72": "Dolnośląskie",
            "PL.78": "Mazowieckie",
        }

        catalog = load_region_catalog()

        pl_regions = catalog["Europe"]["Poland"]
        assert "Dolnośląskie" in pl_regions, "PL.72 should display as 'Dolnośląskie'"
        assert "Mazowieckie" in pl_regions, "PL.78 should display as 'Mazowieckie'"
        # Raw numeric codes must NOT appear as region names
        assert "72" not in pl_regions
        assert "78" not in pl_regions

    @patch("map_tiles_downloader.regions._load_admin1_names")
    @patch("map_tiles_downloader.regions.geonamescache")
    def test_raw_code_fallback_when_name_missing(self, mock_geonamescache, mock_load_names):
        """When no name is found, the raw admin1 code is still used as a fallback."""
        mock_gc = MagicMock()
        mock_geonamescache.GeonamesCache.return_value = mock_gc

        mock_gc.get_continents.return_value = {"EU": {"name": "Europe"}}
        mock_gc.get_countries.return_value = {
            "XY": {
                "continentcode": "EU",
                "name": "Testland",
                "iso": "XY",
            }
        }
        mock_gc.get_subdivisions = None
        mock_gc.get_cities.return_value = {
            "1": {"countrycode": "XY", "admin1code": "99", "latitude": "50.0", "longitude": "10.0"},
        }
        # admin1_names.json has no entry for XY.99
        mock_load_names.return_value = {}

        catalog = load_region_catalog()

        xy_regions = catalog["Europe"]["Testland"]
        # The raw code "99" should appear as the region name
        assert "99" in xy_regions


class TestRegionCatalogStructure:
    """Test the structure and types of the loaded catalog"""

    @patch("map_tiles_downloader.regions.geonamescache")
    def test_catalog_type_annotations(self, mock_geonamescache):
        # Ensure the catalog matches the expected type structure
        mock_gc = MagicMock()
        mock_geonamescache.GeonamesCache.return_value = mock_gc

        mock_gc.get_continents.return_value = {"EU": {"name": "Europe"}}
        mock_gc.get_countries.return_value = {
            "FR": {
                "continentcode": "EU",
                "name": "France",
                "iso": "FR",
                "bbox": {"west": -5.0, "south": 41.0, "east": 10.0, "north": 51.0},
            }
        }
        mock_gc.get_subdivisions.return_value = {}
        mock_gc.get_cities.return_value = {}

        catalog = load_region_catalog()

        # Check types
        assert isinstance(catalog, dict)

        for continent, countries in catalog.items():
            assert isinstance(continent, str)
            assert isinstance(countries, dict)

            for country, states in countries.items():
                assert isinstance(country, str)
                assert isinstance(states, dict)

                for state, bbox in states.items():
                    assert isinstance(state, str)
                    assert isinstance(bbox, tuple)
                    assert len(bbox) == 4
                    assert all(isinstance(coord, float) for coord in bbox)
