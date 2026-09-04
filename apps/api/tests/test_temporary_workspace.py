from types import SimpleNamespace

from progress_api.services import temporary_workspace as workspace_module


def test_temporary_workspace_falls_back_when_configured_directory_is_unavailable(
    monkeypatch,
) -> None:
    unavailable = workspace_module.Path("missing-drive:/processing-temp")
    monkeypatch.setattr(
        workspace_module,
        "get_settings",
        lambda: SimpleNamespace(processing_temp_dir=str(unavailable)),
    )
    monkeypatch.setattr(
        workspace_module.Path,
        "mkdir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unavailable")),
    )

    with workspace_module.temporary_workspace(prefix="fallback-test-") as directory:
        assert workspace_module.Path(directory).is_dir()
