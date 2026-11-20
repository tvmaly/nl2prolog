import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", help="run configured LLM translations")


def pytest_collection_modifyitems(config, items):
    import pytest

    live = [item for item in items if item.get_closest_marker("live")]
    if not config.getoption("--run-live"):
        for item in live:
            item.add_marker(pytest.mark.skip(reason="requires --run-live"))
    elif live:
        from dotenv import load_dotenv

        load_dotenv()
        missing = [k for k in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "NL2LOGIC_MODEL")
                   if not os.getenv(k)]
        if missing:
            raise pytest.UsageError("Live translation requires " + ", ".join(missing))
