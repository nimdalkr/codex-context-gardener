# Contributing

Thank you for improving Context Gardener.

1. Create a focused branch.
2. Keep hook behavior deterministic and standard-library-only.
3. Add or update tests for behavior changes.
4. Run `python -m unittest discover -s tests -v` and `python scripts/validate_package.py`.
5. Explain any change that can replace model-visible tool output or write runtime artifacts.

Please avoid adding transcript parsing as a required dependency. Codex documents transcript files as an unstable hook interface; Context Gardener should work from stable event fields whenever possible.
