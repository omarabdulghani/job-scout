import os
from pathlib import Path
from dotenv import load_dotenv

def load_workspace_env(root_dir: str | Path = ".") -> None:
    """Load environment variables from data/.env, migrating legacy .env if needed."""
    root = Path(root_dir).resolve()
    env_path = root / "data" / ".env"
    legacy_env = root / ".env"

    if not env_path.exists() and legacy_env.exists():
        env_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            legacy_env.rename(env_path)
        except OSError:
            # Fallback if rename fails (e.g. cross-device link)
            import shutil
            shutil.copy2(legacy_env, env_path)
            legacy_env.unlink()

    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    elif legacy_env.exists():
        # Edge case: couldn't move it for some reason
        load_dotenv(dotenv_path=legacy_env, override=True)
    else:
        # Load from default locations if none exist
        load_dotenv(override=True)
