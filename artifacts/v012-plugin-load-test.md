# v0.1.2 plugin-load test (real install path)

The duplicate-hooks failure is a runtime plugin-load error that `claude plugin
validate .` and the offline suite do NOT catch. Verified by installing the local
repo as a marketplace into an isolated `CLAUDE_CONFIG_DIR` and reading
`claude plugin list` status (claude 2.1.177).

## Method
```
$env:CLAUDE_CONFIG_DIR = <isolated temp dir>
claude plugin marketplace add C:/Users/haesol/dev/LecturAL
claude plugin install lectural@lectural --scope user
claude plugin list
```

## Before (main, v0.1.1, plugin.json has "hooks": "./hooks/hooks.json")
```
lectural@lectural
  Version: 0.1.1
  Status: ✘ failed to load
  Error: Hook load failed: Duplicate hooks file detected: ./hooks/hooks.json
  resolves to already-loaded file ...\hooks\hooks.json. The standard
  hooks/hooks.json is loaded automatically, so manifest.hooks should only
  reference additional hook files.
```

## After (fix/plugin-hooks-duplicate, v0.1.2, no manifest "hooks" key)
```
lectural@lectural
  Version: 0.1.2
  Status: ✔ enabled
```

Fix: removed the `hooks` key from `.claude-plugin/plugin.json` (the standard
`hooks/hooks.json` Stop hook is auto-loaded). `lectural doctor` now flags a
manifest `hooks` key that points at the auto-loaded file. Isolated config dirs
were used so the user's real `~/.claude` install was untouched.
