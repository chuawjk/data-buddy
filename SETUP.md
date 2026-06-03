# SETUP.md

Human-facing instructions for agentic development. The one-time setup you do **before** running overnight dev.
The agents assume this environment already exists — none of it is in their context (only `CLAUDE.md` is auto-loaded),
so it lives here.

## 1. Prerequisites — the dev container

Development (and the overnight run) happens inside a **dev container**, which doubles as the
security sandbox (it bounds what the agents can reach). On the host you only need:

- **Docker** (or a compatible runtime).
- **VS Code + Dev Containers extension**, or the **`devcontainer` CLI** (`npm i -g @devcontainers/cli`).

Everything else — Python, uv, Node, pnpm, the `gh` CLI, `make` — is installed by the container, so
you never hand-install toolchains on the host.

### `.devcontainer/devcontainer.json`

```jsonc
{
  "name": "data-buddy",
  "image": "mcr.microsoft.com/devcontainers/base:ubuntu-24.04",
  "features": {
    "ghcr.io/devcontainers/features/python:1": { "version": "3.12" },
    "ghcr.io/devcontainers/features/node:1":   { "version": "22" },
    "ghcr.io/devcontainers/features/github-cli:1": {}
  },
  // Install uv + pnpm, then run the project's make install (uv sync, pnpm install,
  // pre-commit install, playwright browsers).
  "postCreateCommand": "curl -LsSf https://astral.sh/uv/install.sh | sh && export PATH=\"$HOME/.local/bin:$PATH\" && corepack enable && corepack prepare pnpm@latest --activate && make install",
  // Vite (5173) and FastAPI/uvicorn (8000).
  "forwardPorts": [5173, 8000],
  // Pass the scoped GitHub token (and provider creds) through from the host env (§2, §5).
  "remoteEnv": {
    "GH_TOKEN": "${localEnv:GH_TOKEN}"
  },
  "customizations": {
    "vscode": {
      "extensions": [
        "charliermarsh.ruff",
        "ms-python.python",
        "dbaeumer.vscode-eslint",
        "esbenp.prettier-vscode"
      ]
    }
  }
}
```

`make install` is expected to: `uv sync`, `pnpm install`, `pre-commit install`, and
`pnpm exec playwright install --with-deps` (Playwright is used for the QA browser seams). Add
`~/.local/bin` to PATH in the container so `uv` resolves in later shells.

Rebuild the container after editing `devcontainer.json` ("Dev Containers: Rebuild Container").

## 2. Scoped GitHub credential

The agents authenticate `gh`/`git` from `GH_TOKEN` in the container env (forwarded from your host
in `remoteEnv` above). Do **not** use your personal account login.

- Create a **fine-grained PAT** or a **GitHub App installation token** scoped to **this one repo**.
- Permissions: **contents (r/w), pull-requests (r/w), issues (r/w)** — nothing else. No admin, no
  secrets, no workflow-file edits, no member management.
- Prefer generating it from a **dedicated bot collaborator** added with **write, not admin** —
  clean audit trail (bot vs. you), one-click revocation.
- Set `GH_TOKEN` in your host shell before launching the container so it forwards in.

## 3. Branch protection (enforce the merge gate in GitHub, not just in prose)

- **`main`:** require a PR, require your review, block force-push and deletion. Makes "agents never
  touch `main`" a hard guarantee even under a successful injection.
- **`develop`:** require the PR flow, and mark the **CI workflow a required status check** so a red
  run actually blocks merge (this is what makes "CI red blocks merge" real, not just prose).

## 4. Secret-scanning push protection

Turn it on for the repo. An accidental credential commit is blocked at push rather than found later.

## 5. Provider credentials

Keep real secrets out of the repo. Put `OPENAI_*`, OpenCode OAuth, etc. in a local `.env` (or a
secret store the container can reach); committed code references them by name and never contains
them. Forward them into the container via `remoteEnv` alongside `GH_TOKEN` if the run needs them.

## 6. `.gitignore`

At minimum:

```
.env
.claude/settings.local.json
```

Commit the rest of `.claude/` (the agent definitions and the `/night` command are the harness and
belong in history) and the `.devcontainer/`. Before the first push, scan the committed
`.claude/settings.json`, the agent files, and `devcontainer.json` to confirm no token, no absolute
path with your username, and no provider credential snuck in — secret-scanning push protection (§4)
is the backstop.

## 7. Verify the setup (run inside the container)

After the container builds, run these from a terminal **inside** it to confirm the toolchain and —
more importantly — that the agents have exactly the GitHub access they need and no more.

### Toolchain present and correct

```bash
uv --version          # uv installed and on PATH
python --version      # Python 3.12.x
node --version        # v22.x
pnpm --version        # pnpm via corepack
gh --version
make --version
pre-commit --version
```

### Project installed (i.e. `make install` ran)

```bash
test -d .venv && echo ".venv created"                 # uv sync ran
uv pip list | head                                    # deps populated
grep -q pre-commit .git/hooks/pre-commit && echo "pre-commit hook installed"
pnpm exec playwright --version                        # browsers/test runner present
make -n test                                          # the make targets resolve
```

### Agent GitHub access — the important checks

```bash
# 1. gh is authenticated, and using the scoped token (NOT your personal login)
gh auth status

# 2. The identity the agents will act as — expect your BOT account, not you
gh api user --jq .login

# 3. The exact permissions the token grants on this repo
gh api repos/<owner>/<repo> --jq '.permissions'
#    Expect:  "push": true,  "admin": false,  "maintain": false
#      push:true   -> agents can branch, PR, and merge into develop   (needed)
#      admin:false -> agents CANNOT change settings/permissions        (intended)
#    If admin is true, the token is over-scoped — re-issue it (§2).

# 4. Token is present in the env, without printing its value
[ -n "$GH_TOKEN" ] && echo "GH_TOKEN is set"
```

### Branch protection — verify from the GitHub UI (or with your own creds)

The agents' scoped token deliberately can't read repo admin settings, so confirm these yourself in
**Settings → Branches**, or with a token that has admin read:

- `main`: requires a PR + your review, force-push and deletion blocked.
- `develop`: requires the PR flow, and the **CI workflow is a required status check** (this is what
  makes a red CI run actually block merge).

### Provider credentials (only if the run needs them in-container)

```bash
[ -n "$OPENAI_API_KEY" ] && echo "provider key present"   # adjust to your var name
```

### Optional live check (non-destructive, self-cleaning)

Confirms feature-branch push and PR creation work end-to-end, then cleans up:

```bash
git switch -c chore/setup-smoke-test
git commit --allow-empty -m "chore: setup smoke test"
git push -u origin chore/setup-smoke-test                 # feature-branch push works
gh pr create --base develop --draft --title "chore: smoke test" --body "verify access"
# ...note the PR number it prints, then:
gh pr close <num> --delete-branch                         # cleanup
git switch develop && git branch -D chore/setup-smoke-test
```

If push (1–3, optional check) succeeds and `admin` is `false`, the agents have precisely the access
the harness assumes: enough to do the work, not enough to change the rules.
