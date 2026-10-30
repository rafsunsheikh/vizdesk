# Releasing vizdesk

vizdesk is one Python package. The npm package and the Homebrew formula are thin wrappers that install that same package, so a release always starts with PyPI.

## 1. PyPI (pip, pipx, uv)

1. Bump `version` in `pyproject.toml` and `src/vizdesk/__init__.py`.
2. Build and upload:
   ```bash
   rm -rf dist && uv build
   uv publish            # needs a PyPI API token (UV_PUBLISH_TOKEN)
   ```
3. Check: `uvx vizdesk --version`.

## 2. npm

The npm package only contains `bin/vizdesk.js`. It runs `uvx`, then `pipx`, and otherwise creates a private virtual environment in `~/.cache/vizdesk/<version>` on first use.

1. Set the same version in `packaging/npm/package.json` (the launcher installs `vizdesk==<that version>`).
2. Publish:
   ```bash
   cd packaging/npm
   npm publish            # needs `npm login`
   ```
3. Check: `npx vizdesk --version`.

Test the launcher before publishing, against a local wheel:

```bash
VIZDESK_LAUNCHER=venv VIZDESK_PIP_SPEC="$PWD/dist/vizdesk-0.2.0-py3-none-any.whl" \
  XDG_CACHE_HOME=/tmp/vz-cache node packaging/npm/bin/vizdesk.js --version
```

## 3. Homebrew (personal tap)

1. Create a public GitHub repo named `homebrew-tap`.
2. Copy `packaging/homebrew/vizdesk.rb` to `Formula/vizdesk.rb` in that repo.
3. After the PyPI upload, fill in `url` and `sha256` from the sdist:
   ```bash
   curl -sL https://pypi.org/pypi/vizdesk/json \
     | jq -r '.urls[] | select(.packagetype=="sdist") | .url, .digests.sha256'
   ```
4. Push. Users run `brew install <your-user>/tap/vizdesk`.
5. Check: `brew install --build-from-source <your-user>/tap/vizdesk && brew test vizdesk`.

The formula installs pandas, numpy and matplotlib from PyPI wheels inside its own virtual environment. That is fine for a personal tap. homebrew-core would instead require every dependency to be declared as a source "resource", and is not a goal for now.
