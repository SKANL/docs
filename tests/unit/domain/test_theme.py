from docs.domain.theme import (
    ThemeColors,
    VisualTheme,
    has_visual_theme,
    resolve_theme_color,
    resolve_visual_theme,
)


def test_empty_config_yields_default_theme():
    assert resolve_visual_theme({}) == VisualTheme()


def test_hex_colors_are_normalised_and_invalid_ones_fall_back():
    theme = resolve_visual_theme(
        {"format": {"visual_theme": {"colors": {"navy": "#0b1f33", "teal": "zzz", "heading_3": "abcdef"}}}}
    )
    assert theme.colors.navy == "0B1F33"
    assert theme.colors.teal == ThemeColors().teal
    assert theme.colors.heading_3 == "ABCDEF"


def test_headings_inherit_navy_and_teal_when_unset():
    theme = resolve_visual_theme({"format": {"visual_theme": {"colors": {"navy": "112233", "teal": "445566"}}}})
    assert (theme.colors.heading_1, theme.colors.heading_2, theme.colors.heading_3) == ("112233", "112233", "445566")


def test_non_numeric_numbers_and_non_mapping_sections_use_defaults():
    theme = resolve_visual_theme({"format": {"visual_theme": {"typography": {"body_size_pt": "big"}, "spacing": 3}}})
    assert theme.typography.body_size_pt == 12
    assert theme.spacing.body_after_pt == 18


def test_has_visual_theme_requires_a_mapping():
    assert has_visual_theme({"format": {"visual_theme": {}}})
    assert not has_visual_theme({"format": {"visual_theme": "x"}})
    assert not has_visual_theme({})


def test_resolve_theme_color_falls_back_to_navy_for_unknown_names():
    theme = resolve_visual_theme({"format": {"visual_theme": {"colors": {"navy": "112233", "teal": "445566"}}}})
    assert resolve_theme_color(theme, "teal") == "445566"
    assert resolve_theme_color(theme, "nope") == "112233"
