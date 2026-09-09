"""원근 앵커 (app/pipeline/prompt.py::_perspective_anchor).

안반데기 결과에서 인물이 풍경을 압도한 원인은, v5의 크기 검산이 난간·문·차량 같은
'알려진 크기의 인공물'에만 기대고 있었다는 것이다. 밭에는 그런 게 없다. eye-level
카메라에서 같은 지면에 선 사람의 눈높이가 지평선에 온다는 것만이 항상 성립한다.
"""

from __future__ import annotations

from app.pipeline.prompt import _perspective_anchor, build_composition_prompt
from app.places.backgrounds import PlaceContext
from app.schemas.generation import AspectRatio


def _place(**overrides) -> PlaceContext:
    base = PlaceContext(name="안반데기", scene_hint="고랭지 배추밭", lighting_hint="맑음")
    return type(base)(**{**base.__dict__, **overrides})


def test_eye_level이면_머리와_발_위치를_수치로_지시한다() -> None:
    text = _perspective_anchor(
        _place(
            camera_perspective="eye-level",
            horizon_position="middle",
            subject_zone="lower-left, ~40% of frame height",
        )
    )

    # 지평선 50%, 키 40% → 머리 상단 48%, 발 88%
    assert "48%" in text and "88%" in text
    assert "horizon" in text.lower()


def test_부감이면_수치를_지어내지_않는다() -> None:
    text = _perspective_anchor(
        _place(
            camera_perspective="high-angle",
            horizon_position="middle",
            subject_zone="center, ~35% of frame height",
        )
    )

    assert "%" not in text


def test_지평선_위치를_모르면_수치를_지어내지_않는다() -> None:
    text = _perspective_anchor(
        _place(camera_perspective="eye-level", horizon_position="", subject_zone="~40%")
    )

    assert "%" not in text


def test_크기_지시가_없으면_지평선_규칙만_넣는다() -> None:
    text = _perspective_anchor(
        _place(
            camera_perspective="eye-level",
            horizon_position="middle",
            subject_zone="lower-left",
        )
    )

    assert "horizon" in text.lower()
    assert "top of the head" not in text


def test_프롬프트에_실제로_치환된다() -> None:
    prompt = build_composition_prompt(
        _place(
            camera_perspective="eye-level",
            horizon_position="middle",
            subject_zone="lower-left, ~40% of frame height",
        ),
        AspectRatio.PORTRAIT,
        [],
    )

    assert "{perspective_anchor}" not in prompt
    assert "Eye line sits on the horizon" in prompt
