from backend import flow
from backend import gpt_normalizer


def test_resolve_media_path_falls_back_to_data_media():
    resolved = flow._resolve_media_path("media/image4.jpg")

    assert resolved.endswith("data/media/image4.jpg")


def test_resolve_media_path_keeps_urls_unchanged():
    assert flow._resolve_media_path("https://example.test/image.jpg") == "https://example.test/image.jpg"


def test_normalizer_media_root_blocks_absolute_escape(tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.png"
    secret.write_bytes(b"image-bytes")

    # Absolute path resolving outside the trusted media root is rejected.
    assert gpt_normalizer.resolve_media_path(str(secret), media_root=media_root) is None


def test_normalizer_media_root_blocks_parent_traversal(tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    (tmp_path / "escape.png").write_bytes(b"image-bytes")

    assert gpt_normalizer.resolve_media_path("../escape.png", media_root=media_root) is None


def test_normalizer_media_root_allows_contained_image(tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    image = media_root / "ok.png"
    image.write_bytes(b"image-bytes")

    resolved = gpt_normalizer.resolve_media_path("media/ok.png", media_root=media_root)

    assert resolved == image.resolve()
