class _PlatformRegistry:
    def is_registered(self, name: str) -> bool:
        return False


platform_registry = _PlatformRegistry()
