import os
import subprocess
import sys
from pathlib import Path
import pytest
from app.core.config import Settings, settings


def test_app_and_scripts_resolve_same_database_name():
    """Verify that backend app config and scripts resolve the exact same database name."""
    backend_dir = Path(__file__).resolve().parent.parent
    scripts_dir = backend_dir / "scripts"
    sys.path.insert(0, str(backend_dir))
    sys.path.insert(0, str(scripts_dir))

    import seed_drones
    import seed_users
    import migrate_roles

    # Settings singleton used across the application
    app_db = settings.MONGODB_DATABASE
    assert app_db == "medical_drone_db"

    # All scripts use the centralized settings module
    assert seed_drones.settings.MONGODB_DATABASE == app_db
    assert seed_users.settings.MONGODB_DATABASE == app_db
    assert migrate_roles.settings.MONGODB_DATABASE == app_db


def test_settings_resolves_backend_env_regardless_of_cwd(tmp_path, monkeypatch):
    """Verify that Settings always loads backend/.env regardless of os.getcwd()."""
    backend_dir = Path(__file__).resolve().parent.parent
    root_dir = backend_dir.parent

    # Test 1: From backend directory
    monkeypatch.chdir(backend_dir)
    s_backend = Settings()
    assert s_backend.MONGODB_DATABASE == "medical_drone_db"

    # Test 2: From project root directory
    monkeypatch.chdir(root_dir)
    s_root = Settings()
    assert s_root.MONGODB_DATABASE == "medical_drone_db"

    # Test 3: From an arbitrary outside temporary directory
    monkeypatch.chdir(tmp_path)
    s_tmp = Settings()
    assert s_tmp.MONGODB_DATABASE == "medical_drone_db"

    assert s_backend.MONGODB_DATABASE == s_root.MONGODB_DATABASE == s_tmp.MONGODB_DATABASE


def test_cli_scripts_print_same_database_name_from_any_cwd(monkeypatch):
    """Verify CLI execution from root and backend directories outputs the same database name."""
    backend_dir = Path(__file__).resolve().parent.parent
    root_dir = backend_dir.parent

    # Run seed_users --help from backend dir
    res_backend = subprocess.run(
        [sys.executable, "scripts/seed_users.py", "--help"],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    first_line_backend = res_backend.stdout.strip().splitlines()[0]
    assert first_line_backend == f"Using database: {settings.MONGODB_DATABASE}"

    # Run seed_users --help from root dir
    res_root = subprocess.run(
        [sys.executable, "backend/scripts/seed_users.py", "--help"],
        cwd=str(root_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    first_line_root = res_root.stdout.strip().splitlines()[0]
    assert first_line_root == f"Using database: {settings.MONGODB_DATABASE}"
