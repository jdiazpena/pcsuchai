"""Allow ``python -m pcsuchai`` execution without installing an entry point."""

from .cli import main

raise SystemExit(main())
