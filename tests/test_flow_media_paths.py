from backend import flow


def test_resolve_media_path_falls_back_to_data_media():
    resolved = flow._resolve_media_path("media/image4.jpg")

    assert resolved.endswith("data/media/image4.jpg")


def test_resolve_media_path_keeps_urls_unchanged():
    assert flow._resolve_media_path("https://example.test/image.jpg") == "https://example.test/image.jpg"
