"""Compatibility launcher for existing python app.py commands."""
from backend.app import create_app
from backend.cli import main

if __name__ == '__main__':
    main()
