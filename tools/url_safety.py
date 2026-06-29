def is_safe_url(url: str, *_args, **_kwargs) -> bool:
    value = str(url or "").strip().lower()
    return value.startswith(("http://", "https://"))
