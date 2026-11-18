# ECC Integration Guide for u2Lighter

This document explains how the four reference repositories are integrated into the u2Lighter ECC (Engineering Control Center) framework.

## Architecture Overview

```
u2Lighter/
├── .ecc/
│   ├── gstack/              # gstack framework (git submodule)
│   ├── graphify/            # Knowledge graph outputs
│   └── ecc.json             # ECC configuration
├── scripts/
│   └── setup_ecc.py         # ECC setup script
├── pipeline/                # u2Lighter core pipeline
├── automation/              # Custom order automation
├── business/                # Business toolkit
├── marketing/               # Marketing automation
└── ecc.json                 # ECC configuration
```

## 1. gstack Integration (garrytan/gstack)

**Purpose**: AI engineering team framework - provides slash commands for the full sprint lifecycle.

### Integration Points

| gstack Skill | u2Lighter Usage |
|--------------|-----------------|
| `/office-hours` | Product design for new figures (Design Pack creation) |
| `/plan-ceo-review` | Strategic review of new figure designs |
| `/plan-eng-review` | Architecture review of pipeline changes |
| `/plan-design-review` | Design review of case/stand aesthetics |
| `/plan-devex-review` | DX review of CLI tools and APIs |
| `/review` | Code review of pipeline scripts |
| `/qa` | Testing of render outputs, STL validation |
| `/ship` | Release pipeline for new figure versions |
| `/cso` | Security audit of webhook handlers |
| `/document-generate` | Auto-generate docs for pipeline APIs |
| `/retro` | Weekly retrospective on pipeline performance |

### Installation
```bash
cd .ecc/gstack && ./setup --host claude
```

### Usage in u2Lighter
```bash
# Design a new figure
/office-hours "Design a new panther figure for 3D printing"

# Review pipeline changes
/plan-eng-review

# QA test new render
/qa output/marketing/panter_v2/

# Ship new figure release
/ship
```

## 2. graphify Integration (Graphify-Labs/graphify)

**Purpose**: Knowledge graph for codebase navigation - cuts token spend by 80%.

### Integration Points

| Feature | u2Lighter Usage |
|---------|-----------------|
| Code graph | Navigate pipeline scripts (geometry, render, automation) |
| Cross-file links | Trace dependencies between geometry → render → marketing |
| Query API | Ask "How does build_variants.py use variant_matrix.json?" |
| Path tracing | Trace "design_pack → geometry_overrides → case config" |
| God nodes | Find central concepts (config.json, common.py, io3mf.py) |
| Communities | Auto-detect subsystems (geometry, render, automation) |

### Installation
```bash
uv tool install graphifyy
graphify install
```

### Usage in u2Lighter
```bash
# Build knowledge graph
graphify .

# Query the pipeline
graphify query "How does variant matrix affect geometry?"
graphify path "design_pack/panter_v1.json" "pipeline/geometry/build_case_v2.py"
graphify explain "config.json"

# View in browser
open .ecc/graphify/graph.html
```

### Integration with gstack
- `/review` uses graphify to trace code paths
- `/qa` uses graphify to find test coverage gaps
- `/document-generate` uses graphify to understand code structure

## 3. superpowers Integration (obra/superpowers)

**Purpose**: Spec-driven methodology with subagent workflow.

### Integration Points

| Principle | u2Lighter Application |
|-----------|----------------------|
| Spec-first | Design Pack JSON is the spec for each figure |
| TDD | Variant tests in `build_variants.py` validate geometry |
| YAGNI | Minimal config, only override what's needed |
| DRY | Shared `common.py` and `io3mf.py` across pipeline |
| Subagent workflow | `build_variants.py` spawns sub-agents per variant |
| Spec chunks | Design Pack split into geometry/render/marketing |

### Installation
```bash
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

### Usage in u2Lighter
```bash
# Superpowers guides the agent through:
/superpowers-init

# The agent will:
# 1. Ask for Design Pack spec
# 2. Generate implementation plan
# 3. Execute via subagent-driven-development
# 4. Review and test each step
```

### Integration with Pipeline
- Design Pack → Spec
- `run_all.py` → Implementation plan
- `build_variants.py` → Subagent-driven variant generation
- `/review` → Validation gate

## 4. claude-mem Integration (thedotmack/claude-mem)

**Purpose**: Persistent memory across sessions - agent remembers context.

### Integration Points

| Feature | u2Lighter Benefit |
|---------|-------------------|
| Session memory | Remembers figure parameters, design decisions |
| Project memory | Learns pipeline patterns, common fixes |
| Cross-agent | Works with Claude Code, Codex, Cursor |
| Local-first | Memory stays on machine, cloud sync opt-in |

### Installation
```bash
npx claude-mem install
```

### Usage in u2Lighter
```bash
# Memory automatically captures:
# - Figure design decisions
# - Pipeline parameter tuning
# - Render settings that work
# - Common build failures and fixes

# Next session starts with:
# "Last time we tuned panter_v2 light_scale to 0.25 for better renders..."
```

## Unified ECC Workflow

### Daily Development Flow

```bash
# 1. Start session - memory restores context
claude-mem recall

# 2. Design new figure
/office-hours "Design a wolf figure for 3D printing"
# → Creates design_pack/wolf_v1.json

# 3. Plan with superpowers methodology
# Agent generates plan, splits into subagent tasks

# 4. Execute with gstack pipeline
cd pipeline/geometry && python run_all.py --design-pack ../../design_pack/wolf_v1.json

# 5. Variant testing
python build_variants.py --design-pack ../../design_pack/wolf_v1.json --matrix variant_matrix.json

# 6. Knowledge graph for review
graphify query "How does wolf_v1 differ from panter_v1?"

# 7. Review with gstack
/review

# 8. QA test
/qa output/marketing/wolf_v1/

# 8. Ship
/ship
```

### Weekly Retrospective
```bash
/retro
# Reviews:
# - Pipeline performance (build times, success rates)
# - Design quality (render metrics, print success)
# - Business metrics (cost per figure, margin)
# - Memory insights (what patterns emerged)
```

## Configuration

All integration settings in `ecc.json`:

```json
{
  "ecc": {
    "gstack_path": ".ecc/gstack",
    "skills": { "enabled": [...], "custom_skills": [...] },
    "integrations": {
      "graphify": { "enabled": true, "mode": "local" },
      "superpowers": { "enabled": true, "spec_driven": true },
      "claude_mem": { "enabled": true, "sync": "opt-in" }
    }
  },
  "u2lighter": {
    "pipeline": {...},
    "design_pack": {...},
    "variant_testing": {...},
    "custom_orders": {...},
    "marketing_automation": {...}
  }
}
```

## Setup Commands

```bash
# Full setup
python scripts/setup_ecc.py --install

# Check status
python scripts/setup_ecc.py --status

# Run specific tools
python scripts/setup_ecc.py --office-hours "New figure design"
python scripts/setup_ecc.py --review
python scripts/setup_ecc.py --qa
python scripts/setup_ecc.py --graphify
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| gstack not found | Run `python scripts/setup_ecc.py --install` |
| graphify not building | Check `uv tool install graphifyy` worked |
| Memory not persisting | Check `npx claude-mem status` |
| Superpowers not loading | Reinstall plugin: `/plugin install superpowers@superpowers-marketplace` |
| gstack hooks failing | Run `./setup --host claude` in `.ecc/gstack` |

## References

- [gstack docs](https://github.com/garrytan/gstack/tree/main/docs)
- [graphify docs](https://docs.graphify.com)
- [superpowers marketplace](https://github.com/obra/superpowers-marketplace)
- [claude-mem docs](https://docs.claude-mem.ai)