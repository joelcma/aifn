# aifn

AI-assisted local function registry CLI.

The idea:

1. Call a function from the terminal.
2. If it exists, run it locally.
3. If it does not exist, look for similar capabilities or aliases.
4. If nothing matches, scaffold a new generated function.
5. Use the placeholder provider by default, or switch generation to OpenAI.
6. Generated functions are Python by default, with optional Bash scaffolding for shell-native tasks.

## Install locally

```bash
cd aifn
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

To enable OpenAI-backed generation:

```bash
pip install -e '.[openai]'
export OPENAI_API_KEY=your_api_key
export AIFN_FAST_MODEL=gpt-5.4-nano
export AIFN_MAIN_MODEL=gpt-5.4-mini
```

## Try it

```bash
aifn init

aifn call slugify "Hello World"

aifn list

aifn inspect slugify

aifn alias make_slug slugify

aifn call make_slug "Hello Again"

aifn call summarize_text "Some long text" --desc "Return a short summary"

aifn call slugify "Hello World" --language bash --desc "Slugify shell input"
```

## Project layout

```text
.aifn/
  registry.json
  functions/
    slugify.py
  tests/
```

`aifn init` now prompts for the project provider once and stores it in `.aifn/registry.json`, so normal `aifn call ...` usage reuses that provider without needing `--provider` each time. You can still pass `--provider` on a single call to override the saved default.

With the OpenAI provider, `AIFN_FAST_MODEL` is used to classify ambiguous requests such as whether a missing name should become an alias for an existing capability, and `AIFN_MAIN_MODEL` is used only when new code needs to be generated.

Use `aifn config` to inspect the saved project provider and model settings, `aifn config set-provider ...` to change the provider, and `aifn config set-models --main ... --fast ...` to persist project-specific model overrides.

Use `aifn call ... --language bash` when you want a generated shell script instead of Python. Existing execution, inspect, rename, and remove flows work with either `.py` or `.sh` entrypoints.

Use `aifn doctor` to check the saved provider, effective model settings, OpenAI dependency and API key availability, and whether registered function entrypoints exist on disk.
