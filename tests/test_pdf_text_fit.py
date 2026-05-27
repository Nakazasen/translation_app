import math

from translation_app.core.file_handlers.pdf_text_fit import (
    PDFTextFitRequest,
    fit_text_to_bbox,
    summarize_fit_results,
    wrap_text_to_width,
)


def test_fit_short_text_without_overflow():
    result = fit_text_to_bbox(
        PDFTextFitRequest(
            text="Hello world",
            bbox=(0.0, 0.0, 240.0, 80.0),
            font_name="helv",
            font_size=14.0,
        )
    )

    assert result.overflow is False
    assert result.lines == ["Hello world"]
    assert math.isclose(result.font_size, 14.0)
    assert math.isclose(result.scale_ratio, 1.0)


def test_wraps_long_latin_text_to_multiple_lines():
    result = fit_text_to_bbox(
        PDFTextFitRequest(
            text="This is a longer translated sentence that should wrap across multiple lines.",
            bbox=(0.0, 0.0, 150.0, 120.0),
            font_name="helv",
            font_size=12.0,
        )
    )

    assert len(result.lines) > 1
    assert result.overflow is False


def test_shrinks_font_when_height_overflows():
    result = fit_text_to_bbox(
        PDFTextFitRequest(
            text="Wrap this sentence into several lines so the fitter needs to shrink the font size.",
            bbox=(0.0, 0.0, 130.0, 36.0),
            font_name="helv",
            font_size=12.0,
            min_font_size=6.0,
        )
    )

    assert result.font_size < 12.0
    assert result.scale_ratio < 1.0
    assert ("font_shrunk" in result.warnings) or (result.overflow is False)


def test_marks_overflow_when_min_font_reached():
    result = fit_text_to_bbox(
        PDFTextFitRequest(
            text="This translated paragraph is far too long for a tiny annotation box.",
            bbox=(0.0, 0.0, 32.0, 10.0),
            font_name="helv",
            font_size=12.0,
            min_font_size=6.0,
        )
    )

    assert result.overflow is True
    assert result.overflow_reason == "text_overflow"
    assert "text_overflow" in result.warnings
    assert "bbox_too_small" in result.warnings


def test_wraps_cjk_without_spaces():
    text = "\u65e5\u672c\u8a9e\u4e2d\u6587\u65e5\u672c\u8a9e\u4e2d\u6587\u65e5\u672c\u8a9e\u4e2d\u6587"
    result = fit_text_to_bbox(
        PDFTextFitRequest(
            text=text,
            bbox=(0.0, 0.0, 70.0, 120.0),
            font_name="cjk_font",
            font_size=12.0,
            language_hint="ja",
        )
    )

    assert len(result.lines) > 1
    assert result.overflow is False
    assert "".join(result.lines) == text


def test_empty_text_fit_is_safe():
    result = fit_text_to_bbox(
        PDFTextFitRequest(
            text="",
            bbox=(0.0, 0.0, 100.0, 40.0),
            font_name="helv",
            font_size=12.0,
        )
    )

    assert result.lines == []
    assert result.overflow is False
    assert result.fitted_text == ""


def test_summarize_fit_results_counts_overflow():
    ok_result = fit_text_to_bbox(
        PDFTextFitRequest(
            text="Short text",
            bbox=(0.0, 0.0, 160.0, 40.0),
            font_name="helv",
            font_size=12.0,
        )
    )
    overflow_result = fit_text_to_bbox(
        PDFTextFitRequest(
            text="Overflow text that cannot fit into a tiny bounding box at all.",
            bbox=(0.0, 0.0, 30.0, 10.0),
            font_name="helv",
            font_size=12.0,
        )
    )

    summary = summarize_fit_results([ok_result, overflow_result])

    assert summary["result_count"] == 2
    assert summary["overflow_count"] == 1
    assert "warning_counts" in summary
    assert "Overflow text" not in repr(summary)


def test_wrap_text_to_width_splits_long_token_conservatively():
    lines = wrap_text_to_width(
        "supercalifragilisticexpialidocious",
        max_width=60.0,
        font_size=12.0,
        font_name="helv",
    )

    assert len(lines) > 1
    assert "".join(lines) == "supercalifragilisticexpialidocious"
