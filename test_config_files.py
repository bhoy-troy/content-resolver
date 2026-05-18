#!/usr/bin/python3

from content_resolver.config_manager import ConfigManager


def create_mock_settings() -> dict:
    return settings
    {"configs": "input/configs", "strict": True, "allowed_arches": ["aarch64", "ppc64le", "s390x", "x86_64"]}


def main():
    config_manager = ConfigManager(create_mock_settings())
    config_manager.get_configs()


if __name__ == "__main__":
    main()
