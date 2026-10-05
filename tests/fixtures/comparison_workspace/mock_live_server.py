"""Browser-only mock server. Real provider adapters + actual API/storage; SDK transport replaced."""
import argparse
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import uvicorn

from app.comparison_workspace_api import create_app
from tests.fixtures.comparison_workspace.mock_live_sdk import response_for


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    # Explicitly discard environment credentials in the test child; no .env loading.
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "COMPARISON_OPENAI_MODEL", "COMPARISON_DEEPSEEK_MODEL"):
        os.environ.pop(name, None)
    os.environ["DISABLE_LIVE_API"] = "false"
    sdk = Mock()
    sdk.responses.parse.side_effect = response_for
    sdk.responses.create.side_effect = response_for
    sdk.models.list.return_value = SimpleNamespace(data=[SimpleNamespace(id=name) for name in
                                                    ("mock-openai", "deepseek-flash", "deepseek-v4-pro")])
    with patch("openai.OpenAI", return_value=sdk):
        uvicorn.run(create_app(data_dir=args.data_dir), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
