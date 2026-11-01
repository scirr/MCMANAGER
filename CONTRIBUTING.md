# Contributing

Thanks for your interest in MC Manager. Bug reports, ideas and pull requests are welcome.

## Reporting a bug

Open an issue with the bug report form and include the output of:

```
mc doctor --json
```

It lists your version, system and server setup without changing anything. Remove anything private before pasting. For a security problem, do not open an issue: follow [SECURITY.md](SECURITY.md).

## Suggesting an idea

Open an issue with the feature request form. Describe the problem you want solved before the solution.

## Running the tests

```
cd core && python3 -m unittest discover tests
```

The desktop apps have their own tests, run by the jobs of [ci.yml](.github/workflows/ci.yml):

- Linux app: `cd apps/linux && python3 -m unittest discover tests` (view tests need GTK 4 and libadwaita)
- Windows app libraries: `dotnet test apps/windows/MCManager.Client.Tests` and `dotnet test apps/windows/MCManager.ViewModels.Tests`
- macOS app: `cd apps/macos && swift build && swift test`

CI also runs `ruff check core Linux Windows tools packaging` and `bandit`.

## Style

- Python standard library only: no runtime dependency in `core/`.
- Every user-facing string exists in French and English (`core/mc_lang.py`).
- Keep pull requests small and focused, with a test for each fix.
- Documentation is in English.
