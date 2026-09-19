from app.places.backgrounds import PlaceContext, resolve_place_context
from app.places.placement_overrides import PlacementOverride, get_placement_override

JUMUNJIN_BOARDWALK = "https://tong.visitkorea.or.kr/cms2/website/03/2828703.jpg"
JUMUNJIN_LIGHTHOUSE = "https://tong.visitkorea.or.kr/cms2/website/04/2828704.jpg"


def _context(url: str) -> PlaceContext:
    return resolve_place_context(
        "any",
        place_name="주문진 등대",
        place_region=None,
        place_description=None,
        background_image_url=url,
    )


def test_jumunjin_boardwalk_is_confined_between_railings():
    context = _context(JUMUNJIN_BOARDWALK)

    assert "between its two railings" in context.subject_zone
    assert "boardwalk" in context.ground_plane
    assert "plaza" not in context.ground_plane
    assert context.occluding_elements == ""
    assert "나무 데크 길 위" in context.pose_direction
    assert "등대 입구" not in context.pose_direction


def test_other_photos_of_same_place_keep_their_analysis():
    context = _context(JUMUNJIN_LIGHTHOUSE)

    assert "boardwalk" not in context.subject_zone
    assert "등대 입구" in context.pose_direction


def test_unmatched_or_missing_url_has_no_override():
    assert get_placement_override(None) is None
    assert get_placement_override("https://example.com/not-listed.jpg") is None


def test_apply_changes_only_given_fields():
    base = PlaceContext(
        "장소",
        "장면",
        "조명",
        subject_zone="left",
        ground_plane="grass",
        occluding_elements="fence",
        pose_direction="원래 지침",
        pose_negative="원래 금지",
    )

    unchanged = PlacementOverride().apply(base)
    assert unchanged == base

    cleared = PlacementOverride(occluding_elements=()).apply(base)
    assert cleared.occluding_elements == ""
    assert cleared.subject_zone == "left"
    assert cleared.pose_direction == "원래 지침"

    reposed = PlacementOverride(pose_direction="새 지침").apply(base)
    assert reposed.pose_direction == "새 지침"
    assert reposed.pose_negative == ""
