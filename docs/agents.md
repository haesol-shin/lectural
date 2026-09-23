# Using LecturAL with coding agents

LecturAL is a CLI with a versioned JSON contract. Agents run commands, check exit codes, and read `evidence.json`. The [LecturAL skill](../skills/lectural/SKILL.md) teaches that routine: route requests to `extract`, `inspect`, `verify`, or `notes`; cite evidence by segment and frame ID; and do not interpret the media yourself.

## What every host needs

1. The `lectural` command on `PATH` with its runtime ready (the Claude Code plugin provides its own; see below). Install it as in the [README](../README.md#install), then run:

   ```bash
   lectural doctor --fix
   ```

   Exit `0` means ready; exit `2` requires addressing a missing/incompatible item, and exit `1` is an internal or unfixable failure. See the [doctor contract](contracts/cli.md#doctor).

2. The [skill directory](../skills/lectural/) (`SKILL.md` plus `references/`) in a location the host discovers. Keep the directory name `lectural`, matching the skill's `name`.
3. The [skill's hard-failure rule](../skills/lectural/SKILL.md#hard-rules): if a command exits non-zero, stop and report the diagnostic instead of producing an unsupported answer. Other hosts do not have Claude Code's Stop hook.

## Claude Code

In the Claude Code CLI, install the plugin. It includes the skill, `/lectural:notes`, `/lectural:setup`, and a Stop hook that blocks completion until generated notes pass the completeness gate.

```text
/plugin marketplace add haesol-shin/lectural
/plugin install lectural@lectural
/lectural:setup
```

The plugin uses [uv](https://docs.astral.sh/uv/getting-started/installation/) and its lockfile rather than a separate `pip install`; it also needs `ffmpeg` on `PATH` (see [Install](../README.md#install)). `/lectural:setup` installs the locked Python runtime and runs `lectural doctor --fix --plugin` from the plugin root. A successful doctor exits `0`; if setup reports missing components, follow its hints. Then:

```text
/lectural:notes https://youtu.be/<VIDEO_ID>
/lectural:notes ./recording.mp4 --skip-ocr
```

After a successful `/lectural:notes` run, Claude enriches `notes.md` following [`references/summary_prompt.md`](../skills/lectural/references/summary_prompt.md). For evidence only, ask Claude Code, “Extract evidence from ./recording.mp4 without generating notes”; the skill runs `lectural extract` and cites `evidence.json` directly.

## Codex

Codex loads skills from `.agents/skills/` in the repository you work in (from the current directory up to the repository root) and from `$HOME/.agents/skills/` for every repository, and it follows symlinked skill folders ([Codex skills documentation](https://learn.chatgpt.com/docs/build-skills)). In a POSIX shell, choose a stable parent directory for the clone and run:

```bash
git clone https://github.com/haesol-shin/lectural.git
mkdir -p ~/.agents/skills
ln -s "$PWD/lectural/skills/lectural" ~/.agents/skills/lectural
```

On Windows PowerShell, clone the repository in a stable parent directory, then run `New-Item -ItemType Directory -Force "$HOME\.agents\skills"` and `Copy-Item -Recurse lectural\skills\lectural "$HOME\.agents\skills\lectural"` from that parent directory instead. If you move a symlinked clone later, relink it.

Start a new Codex session, then ask for evidence in plain language ("extract evidence from ./lecture.mp4 and tell me where gradient descent is explained") or mention the skill explicitly with `$lectural`. In the LecturAL checkout, Codex also loads applicable repository instructions such as `AGENTS.md` unless an `AGENTS.override.md` takes precedence; this is separate from installing the skill for work in other repositories.

## omp and other skill-aware agents

Agents that support the [Agent Skills](https://agentskills.io/specification) layout discover `<skills-dir>/<name>/SKILL.md`. Clone LecturAL as shown above, then put or link the [skill directory](../skills/lectural/) into the directory your agent scans:

| Agent | User-level skills directory |
|---|---|
| omp | `~/.agents/skills/` (native; the Codex link above also serves omp) |
| Claude Code without the plugin | `~/.claude/skills/` |
| Other agents | the agent's documented skills directory |

An agent without skill support can still use LecturAL. Give it the rules from [`SKILL.md`](../skills/lectural/SKILL.md) as instructions and point it to the [CLI and evidence contract](contracts/cli.md).

## Updating

Upgrade the CLI (`pip install -U "lectural[run]"` or `uv tool upgrade lectural`), then run `git pull` inside your clone; symlinked skills update with it. Check that the skill and CLI agree with `lectural --version --json`: the contract version the skill expects is listed in `supported_contract_versions`.
