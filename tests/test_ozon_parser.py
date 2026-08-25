from app.ozon_parser import (
    fetch_product_data_and_reviews,
    make_review_record,
    parse_product_jsonld,
    project_for_analysis,
    sanitize_error,
    save_archive,
)


def test_jsonld_product_fields_are_normalized():
    result = parse_product_jsonld(
        [
            (
                '{"@type":"Product","brand":{"name":"Fairy"},'
                '"category":"Дом","offers":{"price":"199"}}'
            )
        ]
    )

    assert result == {
        "brand": "Fairy",
        "category_path": ["Дом"],
        "price": "199",
    }


def test_review_records_keep_id_and_analysis_projection():
    record = make_review_record("r-1", "Полезный текст", rating=5)

    assert record["review_id"] == "r-1"
    assert project_for_analysis([record]) == [
        {"text": "Полезный текст", "pros": None, "cons": None, "rating": 5}
    ]


def test_compatibility_wrapper_returns_texts_from_archive(monkeypatch):
    monkeypatch.setattr(
        "app.ozon_parser.fetch_product_archive_and_reviews",
        lambda *args, **kwargs: (
            {"product": {"name": "X"}, "reviews": [{"text": "Текст"}]},
            None,
        ),
    )

    assert fetch_product_data_and_reviews("123456") == (["Текст"], "X", None)


def test_archive_is_written_as_one_product_json(tmp_path):
    path = save_archive(
        {"product": {"article": "123456"}, "reviews": [{"text": "Текст"}]},
        tmp_path,
    )

    assert path == tmp_path / "123456.json"
    assert '"article": "123456"' in path.read_text(encoding="utf-8")


def test_proxy_credentials_are_removed_from_errors():
    message = sanitize_error("request failed: https://user:secret@proxy.example:8080")

    assert "secret" not in message
    assert "***:***@proxy.example" in message
