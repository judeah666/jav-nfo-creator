import unittest
import xml.etree.ElementTree as ET

from app.movie_nfo_editor import (
    DEFAULT_JAVDB_URL_TEMPLATE,
    SUPPORTED_TAGS,
    actor_sortorder_for_display,
    build_backdrop_png_names,
    build_poster_png_name,
    build_part_filename,
    build_matching_video_filename,
    build_javdb_url,
    build_movie_name,
    clean_name,
    contains_supported_tag,
    detect_supported_tag,
    format_actor_list_row,
    format_loaded_genres,
    is_allowed_remote_image_url,
    normalize_supported_tag,
    parse_genre_values,
    parse_multiline_links,
    remove_supported_tags,
)


class MovieNFOEditorHelperTests(unittest.TestCase):
    def test_clean_name_removes_invalid_filename_characters(self):
        self.assertEqual(clean_name('A<Movie>: "Cut"?*'), "AMovie Cut")

    def test_build_movie_name_includes_optional_parts(self):
        self.assertEqual(
            build_movie_name("Tokyo Drift", "2006", "[4K]", "Dong jing piao yi"),
            "TOKYO DRIFT (2006) [4K] - Dong Jing Piao Yi",
        )

    def test_build_movie_name_uses_movie_fallback(self):
        self.assertEqual(build_movie_name("", "", "", ""), "MOVIE")

    def test_build_poster_png_name_uses_filename_stem(self):
        self.assertEqual(build_poster_png_name("SQTE-515 (2024).nfo"), "SQTE-515 (2024)-poster.png")

    def test_build_backdrop_png_name_uses_single_backdrop_suffix(self):
        self.assertEqual(build_backdrop_png_names("SQTE-515 (2024).nfo", 1), ["SQTE-515 (2024)-backdrop.png"])

    def test_build_backdrop_png_name_numbers_multiple_backdrops(self):
        self.assertEqual(
            build_backdrop_png_names("SQTE-515 (2024).nfo", 3),
            [
                "SQTE-515 (2024)-backdrop1.png",
                "SQTE-515 (2024)-backdrop2.png",
                "SQTE-515 (2024)-backdrop3.png",
            ],
        )

    def test_build_matching_video_filename_keeps_video_extension(self):
        self.assertEqual(
            build_matching_video_filename(r"D:\Videos\clip.mkv", "SQTE-515 (2024).nfo"),
            "SQTE-515 (2024).mkv",
        )

    def test_build_part_filename_inserts_part_suffix_before_extension(self):
        self.assertEqual(
            build_part_filename("SQTE-515 (2024).nfo", 2),
            "SQTE-515 (2024)-Part-2.nfo",
        )

    def test_build_matching_video_filename_uses_parted_nfo_name(self):
        self.assertEqual(
            build_matching_video_filename(r"D:\Videos\clip.mkv", build_part_filename("SQTE-515 (2024).nfo", 3)),
            "SQTE-515 (2024)-Part-3.mkv",
        )

    def test_parse_multiline_links_ignores_blank_lines(self):
        self.assertEqual(
            parse_multiline_links("https://one.webp\n\n  https://two.webp  \n"),
            ["https://one.webp", "https://two.webp"],
        )

    def test_is_allowed_remote_image_url_accepts_standard_public_https_url(self):
        self.assertTrue(is_allowed_remote_image_url("https://www.javdatabase.com/poster.webp"))

    def test_is_allowed_remote_image_url_rejects_localhost_and_private_hosts(self):
        self.assertFalse(is_allowed_remote_image_url("http://localhost/poster.webp"))
        self.assertFalse(is_allowed_remote_image_url("http://127.0.0.1/poster.webp"))
        self.assertFalse(is_allowed_remote_image_url("http://192.168.1.5/poster.webp"))

    def test_is_allowed_remote_image_url_rejects_non_standard_ports(self):
        self.assertFalse(is_allowed_remote_image_url("https://example.com:8443/poster.webp"))

    def test_parse_genre_values_splits_comma_separated_values(self):
        self.assertEqual(parse_genre_values("JAV, Action,  Drama "), ["JAV", "Action", "Drama"])

    def test_format_loaded_genres_joins_multiple_genre_tags(self):
        root = ET.fromstring("<movie><genre>JAV</genre><genre>Action</genre></movie>")
        self.assertEqual(format_loaded_genres(root), "JAV, Action")

    def test_format_actor_list_row_orders_columns_as_sort_name_role(self):
        self.assertEqual(
            format_actor_list_row("2", "Ai Abe", "Lead", sort_width=3, name_width=10),
            "  2 | Ai Abe     | Lead",
        )

    def test_supported_tags_are_stable(self):
        self.assertEqual(SUPPORTED_TAGS, ("[Uncen-Leaked]", "[English-Sub]", "[UNCENSORED]", "[4K]"))

    def test_actor_sortorder_for_display_falls_back_to_actor_index(self):
        actor = ET.fromstring("<actor><name>Actor One</name></actor>")
        self.assertEqual(actor_sortorder_for_display(actor, 2), "2")

    def test_detect_supported_tag_is_case_insensitive(self):
        self.assertEqual(detect_supported_tag("sqte-515 [UNCEN-LEAKED].nfo"), "[Uncen-Leaked]")

    def test_remove_supported_tags_is_case_insensitive(self):
        self.assertEqual(remove_supported_tags("SQTE-515 [uncen-leaked]"), "SQTE-515")

    def test_contains_supported_tag_is_case_insensitive(self):
        self.assertTrue(contains_supported_tag("SQTE-515 [UNCEN-LEAKED]", "[Uncen-Leaked]"))

    def test_detect_supported_tag_uses_custom_tags(self):
        tags = ("[Leaked]", "[Subbed]")
        self.assertEqual(detect_supported_tag("movie [LEAKED]", tags), "[Leaked]")

    def test_remove_supported_tags_uses_custom_tags(self):
        tags = ("[Leaked]",)
        self.assertEqual(remove_supported_tags("MOVIE [leaked]", tags), "MOVIE")

    def test_normalize_supported_tag_uses_custom_tags(self):
        tags = ("[Leaked]",)
        self.assertEqual(normalize_supported_tag("[LEAKED]", tags), "[Leaked]")

    def test_default_javdb_url_template_is_stable(self):
        self.assertEqual(DEFAULT_JAVDB_URL_TEMPLATE, "https://www.javdatabase.com/movies/{title}/")

    def test_build_javdb_url_inserts_encoded_title(self):
        self.assertEqual(
            build_javdb_url("https://example.com/search/{title}", "SQTE 515"),
            "https://example.com/search/SQTE%20515",
        )


if __name__ == "__main__":
    unittest.main()
