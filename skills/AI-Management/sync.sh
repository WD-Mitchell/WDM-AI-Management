#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
# sync.sh — Distribute AI content from ~/ai-management to each AI tool
# ─────────────────────────────────────────────────────────────
#
# Usage:
#   ./sync.sh              # sync to project (default)
#   ./sync.sh -g           # sync globally (~/)
#   ./sync.sh --global     # sync globally (~/)
#   ./sync.sh copilot      # sync only to Copilot
#   ./sync.sh codex        # sync only to Codex
#   ./sync.sh claude       # sync only to Claude Code
#   ./sync.sh gemini       # sync only to Gemini CLI
#   ./sync.sh --dry-run            # show what would happen
#   ./sync.sh --refresh            # remove synced symlinks before re-syncing
#   ./sync.sh --purge              # remove all agent files from targets (no re-sync)
#   ./sync.sh --purge --refresh    # purge all files then re-sync fresh
#   ./sync.sh --no-backup          # skip automatic backup before changes
#   ./sync.sh --restore            # interactively choose a backup to restore
#   ./sync.sh --restore-latest     # restore the most recent backup
#   ./sync.sh --restore file.zip   # restore a specific backup file
#   ./sync.sh --pull               # download latest content from GitHub
#   ./sync.sh --group <name>       # sync only items in the named group
#   ./sync.sh --template <name>    # sync items defined in a template (per-project)
#
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
AI_MGMT_DIR="$HOME/ai-management"
AGENTS_HOME="${AI_MANAGEMENT_HOME:-$AI_MGMT_DIR}"

# GitHub source for --pull (configure via environment variables)
GITHUB_REPO="${AI_MANAGEMENT_REPO:-}"
GITHUB_BRANCH="${AI_MANAGEMENT_BRANCH:-main}"

# Detect whether we're running from a local repo checkout
REPO_ROOT=""
if [[ -d "$SCRIPT_DIR/../../agents" ]]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
fi

# Subdirectories to manage
MANAGED_DIRS=(agents skills hooks rules workflows mcp groups templates)

DRY_RUN=false
REFRESH=false
PURGE=false
BACKUP=true
PULL=false
RESTORE=false
RESTORE_LATEST=false
RESTORE_FILE=""
GLOBAL_MODE=false
TARGETS=()
SELECTED_GROUPS=()
TEMPLATE=""

# ── Parse arguments ──────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)        DRY_RUN=true ;;
    --refresh)        REFRESH=true ;;
    --purge)          PURGE=true ;;
    --no-backup)      BACKUP=false ;;
    --pull)           PULL=true ;;
    -g|--global)      GLOBAL_MODE=true ;;
    --group)
      if [[ -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "Error: --group requires a name"; exit 1
      fi
      SELECTED_GROUPS+=("$2"); shift
      ;;
    --template)
      if [[ -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "Error: --template requires a name"; exit 1
      fi
      TEMPLATE="$2"; shift
      ;;
    --restore-latest) RESTORE_LATEST=true ;;
    --restore)
      RESTORE=true
      # If the next arg looks like a filename (not a flag or target), consume it
      if [[ "${2:-}" != "" && "${2:-}" != --* && ! "${2:-}" =~ ^(copilot|codex|claude|gemini)$ ]]; then
        RESTORE_FILE="$2"
        shift
      fi
      ;;
    copilot|codex|claude|gemini) TARGETS+=("$1") ;;
    --help|-h)
      sed -n '3,27p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
  shift
done

# Default: all targets
[[ ${#TARGETS[@]} -eq 0 ]] && TARGETS=(copilot codex claude gemini)

# ── Resolve TARGET_ROOT (project vs global) ──────────────────
if [[ "$GLOBAL_MODE" == true ]]; then
  TARGET_ROOT="$HOME"
else
  # Default to project root (git root or cwd)
  TARGET_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi

# Harness directories derived from TARGET_ROOT
COPILOT_AGENTS_DIR="$TARGET_ROOT/.copilot/agents"
CODEX_DIR="$TARGET_ROOT/.codex"
CODEX_AGENTS_DIR="$TARGET_ROOT/.codex/agents"
CLAUDE_DIR="$TARGET_ROOT/.claude"
GEMINI_DIR="$TARGET_ROOT/.gemini"

# ── Colours ──────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

log()  { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
info() { echo -e "${BLUE}→${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

if [[ "$GLOBAL_MODE" == true ]]; then
  info "Mode: ${BOLD}global${NC} (target: $TARGET_ROOT)"
else
  info "Mode: ${BOLD}project${NC} (target: $TARGET_ROOT)"
fi

# ── Pull: download latest from GitHub ────────────────────────
# Downloads the repo tarball, extracts managed directories into
# ~/ai-management as real files (no local clone needed).
pull_from_github() {
  if [[ -z "$GITHUB_REPO" ]]; then
    err "No repository configured for --pull."
    echo ""
    echo "  Set the AI_MANAGEMENT_REPO environment variable to your GitHub repo:"
    echo "    export AI_MANAGEMENT_REPO=\"your-org/your-ai-management-repo\""
    echo ""
    echo "  Or set it in your shell profile (~/.zshrc, ~/.bashrc)."
    exit 1
  fi

  local api_path="repos/${GITHUB_REPO}/tarball/${GITHUB_BRANCH}"
  local curl_url="https://github.com/${GITHUB_REPO}/archive/refs/heads/${GITHUB_BRANCH}.tar.gz"

  echo ""
  echo -e "${BOLD}── Pulling from GitHub (${GITHUB_REPO}@${GITHUB_BRANCH}) ──${NC}"

  local tmp_dir
  tmp_dir=$(mktemp -d)
  trap 'rm -rf "$tmp_dir"' EXIT

  info "Downloading tarball…"
  local ok=false

  # Try gh CLI first (handles private repos with existing auth)
  if command -v gh &>/dev/null; then
    if gh api "$api_path" 2>/dev/null | tar xz -C "$tmp_dir" 2>/dev/null; then
      ok=true
    fi
  fi

  # Fall back to curl (public repos, no auth required)
  if ! $ok && command -v curl &>/dev/null; then
    if curl -sfL "$curl_url" | tar xz -C "$tmp_dir" 2>/dev/null; then
      ok=true
    fi
  fi

  if ! $ok; then
    err "Failed to download from ${GITHUB_REPO}. Ensure 'gh' is authenticated or the repo is public."
    rm -rf "$tmp_dir"
    exit 1
  fi

  # The tarball extracts into a single directory
  local extracted
  extracted=$(ls -1d "$tmp_dir"/*/ 2>/dev/null | head -1)
  if [[ -z "$extracted" ]]; then
    err "Tarball extraction failed — no directory found"
    rm -rf "$tmp_dir"
    exit 1
  fi

  mkdir -p "$AI_MGMT_DIR"

  for dir in "${MANAGED_DIRS[@]}"; do
    local src="$extracted$dir"
    local dest="$AI_MGMT_DIR/$dir"
    [[ -d "$src" ]] || continue

    # Remove existing symlink — we're replacing with real files
    [[ -L "$dest" ]] && rm -f "$dest"

    # Remove existing real dir and replace with fresh copy
    [[ -d "$dest" ]] && rm -rf "$dest"

    cp -R "$src" "$dest"
    local count
    count=$(find "$dest" -type f 2>/dev/null | wc -l | tr -d ' ')
    log "Pulled $dir/ ($count files)"
  done

  # Also pull defaults.conf and install.sh if present
  [[ -f "$extracted/defaults.conf" ]] && cp "$extracted/defaults.conf" "$AI_MGMT_DIR/defaults.conf"
  [[ -f "$extracted/install.sh" ]] && cp "$extracted/install.sh" "$AI_MGMT_DIR/install.sh" && chmod +x "$AI_MGMT_DIR/install.sh"

  rm -rf "$tmp_dir"
  trap - EXIT

  echo ""
  log "Pull complete → $AI_MGMT_DIR"
}

# ── Setup: ensure ~/ai-management is populated ──────────────
# If a local repo checkout exists, symlinks its subdirs into
# ~/ai-management. Otherwise, checks that ~/ai-management already
# has content (from a previous --pull). If neither, advises
# the user to run --pull.
setup_ai_mgmt_dir() {
  mkdir -p "$AI_MGMT_DIR"

  # If we have a local repo checkout, symlink its dirs
  if [[ -n "$REPO_ROOT" ]]; then
    # Guard: skip if REPO_ROOT resolved to ~/ai-management itself (self-reference)
    local real_mgmt real_repo
    real_mgmt="$(cd "$AI_MGMT_DIR" && pwd -P)"
    real_repo="$(cd "$REPO_ROOT" && pwd -P)"
    if [[ "$real_repo" == "$real_mgmt" ]]; then
      return
    fi

    for dir in "${MANAGED_DIRS[@]}"; do
      local src="$REPO_ROOT/$dir"
      local dest="$AI_MGMT_DIR/$dir"
      [[ -d "$src" ]] || continue
      if [[ -L "$dest" ]]; then
        local current
        current=$(readlink "$dest" 2>/dev/null || true)
        [[ "$current" == "$src" ]] && continue
        rm -f "$dest"
      elif [[ -d "$dest" ]]; then
        # Real directory exists (e.g. from --pull) — skip
        continue
      fi
      ln -s "$src" "$dest"
      info "Linked $dir/ → $dest"
    done
  fi
}

# Run pull if requested
if $PULL; then
  pull_from_github
fi

setup_ai_mgmt_dir

# ── Validation ───────────────────────────────────────────────
if [[ ! -d "$AGENTS_HOME/agents" ]]; then
  err "No agents directory found at $AGENTS_HOME/agents"
  echo ""
  echo "  Run with --pull to download content from GitHub:"
  echo "    $0 --pull"
  echo ""
  echo "  Make sure AI_MANAGEMENT_REPO is set to your GitHub repository."
  exit 1
fi

agent_count=$(find -L "$AGENTS_HOME/agents" -name '*.md' -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')
info "Found ${BOLD}$agent_count${NC} agent files in $AGENTS_HOME/agents/"

# ── Group resolution ─────────────────────────────────────────
# Builds RESOLVED_AGENTS, RESOLVED_SKILLS, RESOLVED_RULES,
# RESOLVED_WORKFLOWS, RESOLVED_MCP arrays from group files.

# Helper: check if array contains a value (Bash 3.2 compatible)
array_contains() {
  local needle="$1"; shift
  local item
  for item in "$@"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

# Helper: expand a wildcard or name list for a given section
resolve_section() {
  local section="$1" dir="$2"
  shift 2
  local -a names=("$@")

  # Wildcard — return all matching files in the directory
  if array_contains "*" "${names[@]}"; then
    case "$section" in
      agents|rules|workflows)
        for f in "$dir"/*.md; do
          [[ -f "$f" ]] || continue
          echo "$f"
        done
        ;;
      skills)
        for d in "$dir"/*/; do
          [[ -d "$d" ]] || continue
          [[ -f "$d/SKILL.md" || -f "$d/skill.md" ]] || continue
          echo "$d"
        done
        ;;
      mcp)
        for f in "$dir"/*.json "$dir"/*.yaml "$dir"/*.yml "$dir"/*.md; do
          [[ -f "$f" ]] || continue
          echo "$f"
        done
        ;;
    esac
    return
  fi

  # Explicit names — resolve each
  local name
  for name in "${names[@]}"; do
    case "$section" in
      agents|rules|workflows)
        local path="$dir/${name}.md"
        if [[ -f "$path" ]]; then
          echo "$path"
        else
          warn "Group entry not found: $section/$name (.md)"
        fi
        ;;
      skills)
        local path="$dir/${name}"
        if [[ -d "$path" ]]; then
          echo "$path/"
        else
          warn "Group entry not found: $section/$name (directory)"
        fi
        ;;
      mcp)
        local found=false
        for ext in md json yaml yml; do
          local path="$dir/${name}.${ext}"
          if [[ -f "$path" ]]; then
            echo "$path"
            found=true
            break
          fi
        done
        $found || warn "Group entry not found: $section/$name (.md/.json/.yaml/.yml)"
        ;;
    esac
  done
}

# Parse a .group file into section arrays
parse_group_file() {
  local group_file="$1"
  local current_section=""

  while IFS= read -r line; do
    # Strip leading/trailing whitespace
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    # Skip blank lines and comments
    [[ -z "$line" || "$line" == \#* ]] && continue
    # Section header
    if [[ "$line" =~ ^\[([a-z]+)\]$ ]]; then
      current_section="${BASH_REMATCH[1]}"
      continue
    fi
    # Entry under a section
    if [[ -n "$current_section" ]]; then
      case "$current_section" in
        agents)    _GRP_AGENTS+=("$line") ;;
        skills)    _GRP_SKILLS+=("$line") ;;
        rules)     _GRP_RULES+=("$line") ;;
        workflows) _GRP_WORKFLOWS+=("$line") ;;
        hooks)     _GRP_HOOKS+=("$line") ;;
        mcp)       _GRP_MCP+=("$line") ;;
        *)         warn "Unknown group section: [$current_section]" ;;
      esac
    fi
  done < "$group_file"
}

# ── Template resolution ───────────────────────────────────────
# Templates combine groups + individual items. If --template is specified,
# parse the template file and add its groups to SELECTED_GROUPS,
# and its individual items directly to the _GRP arrays.
if [[ -n "$TEMPLATE" ]]; then
  TEMPLATE_FILE="$AGENTS_HOME/templates/${TEMPLATE}.template"
  if [[ ! -f "$TEMPLATE_FILE" ]]; then
    err "Template file not found: $TEMPLATE_FILE"
    exit 1
  fi
  info "Applying template: ${BOLD}$TEMPLATE${NC}"

  _TPL_SECTION=""
  while IFS= read -r line; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ "$line" =~ ^\[([a-z]+)\]$ ]]; then
      _TPL_SECTION="${BASH_REMATCH[1]}"
      continue
    fi
    if [[ -n "$_TPL_SECTION" ]]; then
      case "$_TPL_SECTION" in
        groups)    SELECTED_GROUPS+=("$line") ;;
        agents)    _GRP_AGENTS+=("$line") ;;
        skills)    _GRP_SKILLS+=("$line") ;;
        rules)     _GRP_RULES+=("$line") ;;
        workflows) _GRP_WORKFLOWS+=("$line") ;;
        hooks)     _GRP_HOOKS+=("$line") ;;
        mcp)       _GRP_MCP+=("$line") ;;
        *)         warn "Unknown template section: [$_TPL_SECTION]" ;;
      esac
    fi
  done < "$TEMPLATE_FILE"

  # Also save template name to project config if in project mode
  if [[ "$GLOBAL_MODE" == false && "$DRY_RUN" == false ]]; then
    echo "$TEMPLATE" > "$TARGET_ROOT/.ai-management"
    log "Saved template reference → $TARGET_ROOT/.ai-management"
  fi
fi

# If no template and no groups specified, check for project config file
if [[ -z "$TEMPLATE" && ${#SELECTED_GROUPS[@]} -eq 0 ]]; then
  if [[ "$GLOBAL_MODE" == false && -f "$TARGET_ROOT/.ai-management" ]]; then
    _saved_template="$(head -1 "$TARGET_ROOT/.ai-management" | tr -d '[:space:]')"
    if [[ -n "$_saved_template" ]]; then
      TEMPLATE_FILE="$AGENTS_HOME/templates/${_saved_template}.template"
      if [[ -f "$TEMPLATE_FILE" ]]; then
        info "Using project template: ${BOLD}$_saved_template${NC}"
        _TPL_SECTION=""
        while IFS= read -r line; do
          line="${line#"${line%%[![:space:]]*}"}"
          line="${line%"${line##*[![:space:]]}"}"
          [[ -z "$line" || "$line" == \#* ]] && continue
          if [[ "$line" =~ ^\[([a-z]+)\]$ ]]; then
            _TPL_SECTION="${BASH_REMATCH[1]}"
            continue
          fi
          if [[ -n "$_TPL_SECTION" ]]; then
            case "$_TPL_SECTION" in
              groups)    SELECTED_GROUPS+=("$line") ;;
              agents)    _GRP_AGENTS+=("$line") ;;
              skills)    _GRP_SKILLS+=("$line") ;;
              rules)     _GRP_RULES+=("$line") ;;
              workflows) _GRP_WORKFLOWS+=("$line") ;;
              hooks)     _GRP_HOOKS+=("$line") ;;
              mcp)       _GRP_MCP+=("$line") ;;
            esac
          fi
        done < "$TEMPLATE_FILE"
      fi
    fi
  fi
fi

# Default to "default" group when none specified and no template loaded
[[ ${#SELECTED_GROUPS[@]} -eq 0 ]] && SELECTED_GROUPS=(default)

# Collect raw entries from all requested groups
_GRP_AGENTS=()
_GRP_SKILLS=()
_GRP_RULES=()
_GRP_WORKFLOWS=()
_GRP_HOOKS=()
_GRP_MCP=()

for group_name in "${SELECTED_GROUPS[@]}"; do
  local_group_file="$AGENTS_HOME/groups/${group_name}.group"
  if [[ ! -f "$local_group_file" ]]; then
    err "Group file not found: $local_group_file"
    exit 1
  fi
  info "Loading group: ${BOLD}$group_name${NC}"
  parse_group_file "$local_group_file"
done

# Resolve entries to full paths, deduplicating across groups
RESOLVED_AGENTS=()
RESOLVED_SKILLS=()
RESOLVED_RULES=()
RESOLVED_WORKFLOWS=()
RESOLVED_HOOKS=()
RESOLVED_MCP=()

while IFS= read -r p; do
  [[ -n "$p" ]] && ! array_contains "$p" "${RESOLVED_AGENTS[@]}" && RESOLVED_AGENTS+=("$p")
done < <(resolve_section agents "$AGENTS_HOME/agents" "${_GRP_AGENTS[@]+"${_GRP_AGENTS[@]}"}")

while IFS= read -r p; do
  [[ -n "$p" ]] && ! array_contains "$p" "${RESOLVED_SKILLS[@]}" && RESOLVED_SKILLS+=("$p")
done < <(resolve_section skills "$AGENTS_HOME/skills" "${_GRP_SKILLS[@]+"${_GRP_SKILLS[@]}"}")

while IFS= read -r p; do
  [[ -n "$p" ]] && ! array_contains "$p" "${RESOLVED_RULES[@]}" && RESOLVED_RULES+=("$p")
done < <(resolve_section rules "$AGENTS_HOME/rules" "${_GRP_RULES[@]+"${_GRP_RULES[@]}"}")

while IFS= read -r p; do
  [[ -n "$p" ]] && ! array_contains "$p" "${RESOLVED_WORKFLOWS[@]}" && RESOLVED_WORKFLOWS+=("$p")
done < <(resolve_section workflows "$AGENTS_HOME/workflows" "${_GRP_WORKFLOWS[@]+"${_GRP_WORKFLOWS[@]}"}")

while IFS= read -r p; do
  [[ -n "$p" ]] && ! array_contains "$p" "${RESOLVED_HOOKS[@]}" && RESOLVED_HOOKS+=("$p")
done < <(resolve_section hooks "$AGENTS_HOME/hooks" "${_GRP_HOOKS[@]+"${_GRP_HOOKS[@]}"}")

while IFS= read -r p; do
  [[ -n "$p" ]] && ! array_contains "$p" "${RESOLVED_MCP[@]}" && RESOLVED_MCP+=("$p")
done < <(resolve_section mcp "$AGENTS_HOME/mcp" "${_GRP_MCP[@]+"${_GRP_MCP[@]}"}")

info "Group resolved: ${BOLD}${#RESOLVED_AGENTS[@]}${NC} agents, ${#RESOLVED_SKILLS[@]} skills, ${#RESOLVED_RULES[@]} rules, ${#RESOLVED_WORKFLOWS[@]} workflows, ${#RESOLVED_HOOKS[@]} hooks, ${#RESOLVED_MCP[@]} mcp"

# ── Helper: back up agent files before changes ───────────────
backup_path() {
  local label="$1" path="$2"

  local -a files_to_backup=()
  local backup_dir

  if [[ -d "$path" ]]; then
    backup_dir="$path/backups"
    while IFS= read -r -d '' f; do
      files_to_backup+=("$f")
    done < <(find "$path" -maxdepth 1 \( -type f -o -type l \) -print0 2>/dev/null)
  elif [[ -e "$path" ]]; then
    backup_dir="$(dirname "$path")/backups"
    files_to_backup+=("$path")
  fi

  if [[ ${#files_to_backup[@]} -eq 0 ]]; then
    return
  fi

  # Filter to files/file-symlinks only (skip directory symlinks)
  local -a valid_files=()
  for f in "${files_to_backup[@]}"; do
    [[ -f "$f" ]] && valid_files+=("$f")
  done
  if [[ ${#valid_files[@]} -eq 0 ]]; then
    return
  fi

  local type_name
  if [[ -d "$path" ]]; then
    type_name=$(basename "$path")
  else
    type_name=$(basename "$path" | sed 's/\.[^.]*$//')
  fi

  local timestamp
  timestamp=$(date '+%Y%m%d-%H%M%S')
  local zip_file="$backup_dir/${label}-${type_name}-${timestamp}.zip"

  if $DRY_RUN; then
    info "[dry-run] Would back up ${#valid_files[@]} ${type_name} files → $(basename "$zip_file")"
    return
  fi

  mkdir -p "$backup_dir"
  if zip -jq "$zip_file" "${valid_files[@]}" 2>/dev/null; then
    log "$label: backed up ${#valid_files[@]} ${type_name} files → $(basename "$zip_file")"
  fi
}

# ── Helper: resolve all managed paths for a target ───────────
managed_paths_for() {
  case "$1" in
    copilot)
      echo "$COPILOT_AGENTS_DIR"
      echo "$TARGET_ROOT/.copilot/skills"
      echo "$TARGET_ROOT/.copilot/instructions"
      echo "$TARGET_ROOT/.copilot/workflows"
      echo "$TARGET_ROOT/.copilot/hooks"
      [[ -f "$TARGET_ROOT/.copilot/mcp.json" ]] && echo "$TARGET_ROOT/.copilot/mcp.json"
      ;;
    codex)
      echo "$CODEX_AGENTS_DIR"
      echo "$CODEX_DIR/skills"
      echo "$CODEX_DIR/instructions"
      echo "$CODEX_DIR/workflows"
      echo "$CODEX_DIR/hooks"
      [[ -f "$CODEX_DIR/mcp-servers.json" ]] && echo "$CODEX_DIR/mcp-servers.json"
      ;;
    claude)
      echo "$CLAUDE_DIR/agents"
      echo "$CLAUDE_DIR/skills"
      echo "$CLAUDE_DIR/rules"
      echo "$CLAUDE_DIR/workflows"
      echo "$CLAUDE_DIR/hooks"
      [[ -f "$CLAUDE_DIR/mcp.json" ]] && echo "$CLAUDE_DIR/mcp.json"
      ;;
    gemini)
      [[ -f "$GEMINI_DIR/GEMINI.md" ]] && echo "$GEMINI_DIR/GEMINI.md"
      [[ -f "$GEMINI_DIR/mcp-servers.json" ]] && echo "$GEMINI_DIR/mcp-servers.json"
      ;;
  esac
}

# ── Helper: resolve restore directory for a target ───────────
restore_paths_for() {
  local paths=()
  while IFS= read -r p; do
    [[ -n "$p" ]] && paths+=("$p")
  done < <(managed_paths_for "$1")

  for path in "${paths[@]}"; do
    if [[ -d "$path" || ! -e "$path" ]]; then
      local real_path="$path"
      real_path="${real_path%/}"
      echo "${real_path}/backups|${real_path}"
    else
      local parent
      parent=$(dirname "$path")
      echo "${parent}/backups|${parent}"
    fi
  done
}

all_backup_dirs_for() {
  case "$1" in
    copilot)
      echo "$COPILOT_AGENTS_DIR/backups|$COPILOT_AGENTS_DIR"
      echo "$TARGET_ROOT/.copilot/skills/backups|$TARGET_ROOT/.copilot/skills"
      echo "$TARGET_ROOT/.copilot/instructions/backups|$TARGET_ROOT/.copilot/instructions"
      echo "$TARGET_ROOT/.copilot/workflows/backups|$TARGET_ROOT/.copilot/workflows"
      echo "$TARGET_ROOT/.copilot/hooks/backups|$TARGET_ROOT/.copilot/hooks"
      echo "$TARGET_ROOT/.copilot/backups|$TARGET_ROOT/.copilot"
      ;;
    codex)
      echo "$CODEX_AGENTS_DIR/backups|$CODEX_AGENTS_DIR"
      echo "$CODEX_DIR/skills/backups|$CODEX_DIR/skills"
      echo "$CODEX_DIR/instructions/backups|$CODEX_DIR/instructions"
      echo "$CODEX_DIR/workflows/backups|$CODEX_DIR/workflows"
      echo "$CODEX_DIR/hooks/backups|$CODEX_DIR/hooks"
      echo "$CODEX_DIR/backups|$CODEX_DIR"
      ;;
    claude)
      echo "$CLAUDE_DIR/agents/backups|$CLAUDE_DIR/agents"
      echo "$CLAUDE_DIR/skills/backups|$CLAUDE_DIR/skills"
      echo "$CLAUDE_DIR/rules/backups|$CLAUDE_DIR/rules"
      echo "$CLAUDE_DIR/workflows/backups|$CLAUDE_DIR/workflows"
      echo "$CLAUDE_DIR/hooks/backups|$CLAUDE_DIR/hooks"
      echo "$CLAUDE_DIR/backups|$CLAUDE_DIR"
      ;;
    gemini)
      echo "$GEMINI_DIR/backups|$GEMINI_DIR"
      ;;
  esac
}

# ── Helper: restore from a zip backup ────────────────────────
do_restore() {
  local label="$1" backup_dir="$2" restore_dir="$3" zip_file="$4"

  if [[ ! -f "$zip_file" ]]; then
    err "$label: backup not found — $zip_file"
    return 1
  fi

  local file_count
  file_count=$(zipinfo -1 "$zip_file" 2>/dev/null | wc -l | tr -d ' ')

  if $DRY_RUN; then
    info "[dry-run] Would restore $file_count files from $(basename "$zip_file") → $restore_dir"
    return
  fi

  mkdir -p "$restore_dir"
  unzip -joq "$zip_file" -d "$restore_dir" 2>/dev/null
  log "$label: restored $file_count files from $(basename "$zip_file") → $restore_dir/"
}

# ── Helper: run restore for a single target ──────────────────
restore_target() {
  local target="$1"
  local label="$target"

  echo ""
  echo -e "${BOLD}── Restoring $label files ──${NC}"

  if [[ -n "$RESTORE_FILE" ]]; then
    local found=false
    while IFS='|' read -r bdir rdir; do
      local zip_path="$bdir/$RESTORE_FILE"
      [[ -f "$RESTORE_FILE" ]] && zip_path="$RESTORE_FILE"
      if [[ -f "$zip_path" ]]; then
        do_restore "$label" "$bdir" "$rdir" "$zip_path"
        found=true
        break
      fi
    done < <(all_backup_dirs_for "$target")
    if ! $found; then
      err "$label: backup file not found — $RESTORE_FILE"
    fi

  elif $RESTORE_LATEST; then
    local any_found=false
    while IFS='|' read -r bdir rdir; do
      [[ -d "$bdir" ]] || continue
      local latest
      latest=$(ls -1t "$bdir"/*.zip 2>/dev/null | head -1)
      if [[ -n "$latest" ]]; then
        do_restore "$label ($(basename "$rdir"))" "$bdir" "$rdir" "$latest"
        any_found=true
      fi
    done < <(all_backup_dirs_for "$target")
    if ! $any_found; then
      warn "$label: no backups found"
    fi

  else
    local -a all_zips=() all_rdirs=() all_bdirs=()
    while IFS='|' read -r bdir rdir; do
      [[ -d "$bdir" ]] || continue
      while IFS= read -r f; do
        [[ -n "$f" ]] && all_zips+=("$f") && all_rdirs+=("$rdir") && all_bdirs+=("$bdir")
      done < <(ls -1t "$bdir"/*.zip 2>/dev/null)
    done < <(all_backup_dirs_for "$target")

    if [[ ${#all_zips[@]} -eq 0 ]]; then
      warn "$label: no backups found"
      return
    fi

    echo ""
    echo -e "  ${BOLD}Available backups for $label:${NC}"
    local i=1
    for b in "${all_zips[@]}"; do
      local name size type_hint
      name=$(basename "$b")
      size=$(du -h "$b" | cut -f1 | tr -d ' ')
      type_hint=$(basename "${all_rdirs[$((i-1))]}")
      printf "    ${BLUE}%d)${NC} %-50s ${YELLOW}(%s)${NC}  [%s]\n" "$i" "$name" "$size" "$type_hint"
      i=$((i + 1))
    done
    echo ""
    read -rp "  Enter number to restore (or 'q' to skip): " choice

    if [[ "$choice" == "q" || -z "$choice" ]]; then
      info "$label: skipped"
      return
    fi

    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#all_zips[@]} )); then
      local idx=$((choice - 1))
      do_restore "$label" "${all_bdirs[$idx]}" "${all_rdirs[$idx]}" "${all_zips[$idx]}"
    else
      err "Invalid selection"
    fi
  fi
}

# ── Helper: make symlink ─────────────────────────────────────
make_link() {
  local src="$1" dest="$2"
  if $DRY_RUN; then
    info "[dry-run] symlink: $src → $dest"
    return
  fi
  [[ -e "$dest" || -L "$dest" ]] && rm -f "$dest"
  ln -s "$src" "$dest"
}

# ── Helper: safely remove symlinks from a dir ────────────────
purge_symlinks_in() {
  local dir="$1"
  [[ -d "$dir" ]] || return 0
  find "$dir" -maxdepth 1 -type l -not -name backups -not -path "*/backups/*" -delete 2>/dev/null || true
}

# ── Helper: sync skills to a target directory ────────────────
sync_skills_to() {
  local target_dir="$1" harness="$2" label="$3"
  [[ ${#RESOLVED_SKILLS[@]} -eq 0 ]] && return

  if $REFRESH; then
    info "Cleaning existing skill symlinks in $target_dir"
    purge_symlinks_in "$target_dir"
  fi

  local build_dir="$AGENTS_HOME/skills/$harness"
  local skills_count=0
  for skill_dir in "${RESOLVED_SKILLS[@]}"; do
    [[ -d "$skill_dir" ]] || continue
    local skill_name
    skill_name=$(basename "$skill_dir")
    local built_skill="$build_dir/$skill_name"
    [[ -d "$built_skill" ]] || continue
    mkdir -p "$target_dir"
    make_link "$built_skill" "$target_dir/$skill_name"
    skills_count=$((skills_count + 1))
  done
  [[ $skills_count -gt 0 ]] && log "$label: symlinked $skills_count skills → $target_dir/"
}

# ── Helper: sync rules to a target directory ─────────────────
sync_rules_to() {
  local target_dir="$1" harness="$2" label="$3"
  [[ ${#RESOLVED_RULES[@]} -eq 0 ]] && return

  if $REFRESH; then
    purge_symlinks_in "$target_dir"
  fi

  local build_dir="$AGENTS_HOME/rules/$harness"
  local count=0
  for rule_file in "${RESOLVED_RULES[@]}"; do
    [[ -f "$rule_file" ]] || continue
    local rule_name
    rule_name=$(basename "$rule_file")
    local built_rule="$build_dir/$rule_name"
    [[ -f "$built_rule" ]] || continue
    mkdir -p "$target_dir"
    make_link "$built_rule" "$target_dir/$rule_name"
    count=$((count + 1))
  done
  [[ $count -gt 0 ]] && log "$label: symlinked $count rules → $target_dir/"
}

# ── Helper: sync workflows to a target directory ─────────────
sync_workflows_to() {
  local target_dir="$1" harness="$2" label="$3"
  [[ ${#RESOLVED_WORKFLOWS[@]} -eq 0 ]] && return

  if $REFRESH; then
    purge_symlinks_in "$target_dir"
  fi

  local build_dir="$AGENTS_HOME/workflows/$harness"
  local count=0
  for wf_file in "${RESOLVED_WORKFLOWS[@]}"; do
    [[ -f "$wf_file" ]] || continue
    local wf_name
    wf_name=$(basename "$wf_file")
    local built_wf="$build_dir/$wf_name"
    [[ -f "$built_wf" ]] || continue
    mkdir -p "$target_dir"
    make_link "$built_wf" "$target_dir/$wf_name"
    count=$((count + 1))
  done
  [[ $count -gt 0 ]] && log "$label: symlinked $count workflows → $target_dir/"
}

# ── Helper: sync hooks to a target directory ─────────────────
sync_hooks_to() {
  local target_dir="$1" harness="$2" label="$3"
  local build_dir="$AGENTS_HOME/hooks/$harness"
  [[ -d "$build_dir" ]] || return

  local hook_files=()
  while IFS= read -r -d '' f; do
    hook_files+=("$f")
  done < <(find "$build_dir" -maxdepth 1 -type f -print0 2>/dev/null)
  [[ ${#hook_files[@]} -eq 0 ]] && return

  if $REFRESH; then
    purge_symlinks_in "$target_dir"
  fi

  local count=0
  for hook_file in "${hook_files[@]}"; do
    local hook_name
    hook_name=$(basename "$hook_file")
    mkdir -p "$target_dir"
    make_link "$hook_file" "$target_dir/$hook_name"
    count=$((count + 1))
  done
  [[ $count -gt 0 ]] && log "$label: symlinked $count hooks → $target_dir/"
}

# ── Helper: sync MCP config to a harness ─────────────────────
sync_mcp_to() {
  local harness="$1" label="$2"
  [[ ${#RESOLVED_MCP[@]} -eq 0 ]] && return

  local build_dir="$AGENTS_HOME/mcp/$harness"
  [[ -d "$build_dir" ]] || return

  local mcp_entries=()
  for mcp_file in "${RESOLVED_MCP[@]}"; do
    [[ -e "$mcp_file" ]] || continue
    local mcp_name
    mcp_name=$(basename "$mcp_file")
    mcp_name="${mcp_name%.*}"
    local built_mcp="$build_dir/${mcp_name}.json"
    [[ -f "$built_mcp" ]] || continue
    mcp_entries+=("$built_mcp")
  done
  [[ ${#mcp_entries[@]} -eq 0 ]] && return

  local combined
  case "$harness" in
    copilot)
      combined="$TARGET_ROOT/.copilot/mcp.json"
      ;;
    claude)
      combined="$CLAUDE_DIR/mcp.json"
      ;;
    codex)
      combined="$CODEX_DIR/mcp-servers.json"
      ;;
    gemini)
      combined="$GEMINI_DIR/mcp-servers.json"
      ;;
    *)
      return ;;
  esac

  if $DRY_RUN; then
    info "[dry-run] Would write ${#mcp_entries[@]} MCP servers to $combined"
    return
  fi

  local json_content
  json_content=$(python3 -c "
import json, sys, os
servers = {}
for path in sys.argv[1:]:
    with open(path) as f:
        data = json.load(f)
    name = os.path.splitext(os.path.basename(path))[0]
    servers[name] = data
print(json.dumps({'mcpServers': servers}, indent=2))
" "${mcp_entries[@]}")

  mkdir -p "$(dirname "$combined")"
  echo "$json_content" > "$combined"
  log "$label: wrote ${#mcp_entries[@]} MCP servers → $combined"
}

# ── Helper: build harness-specific files for all content types ──
build_all() {
  local harnesses="$1"
  local build_script="$AGENTS_HOME/skills/AI-Management/build.py"

  # Also check in SCRIPT_DIR (if running from repo checkout)
  if [[ ! -f "$build_script" && -f "$SCRIPT_DIR/build.py" ]]; then
    build_script="$SCRIPT_DIR/build.py"
  fi

  if [[ ! -f "$build_script" ]]; then
    err "Build script not found: $build_script"
    exit 1
  fi

  if ! command -v python3 &>/dev/null; then
    err "python3 is required for the build step but was not found"
    exit 1
  fi

  local types=("agents" "skills" "rules" "workflows" "mcp" "hooks")

  for content_type in "${types[@]}"; do
    local source_dir="$AGENTS_HOME/$content_type"
    [[ -d "$source_dir" ]] || continue

    local has_sources=false
    case "$content_type" in
      agents|rules|workflows)
        [[ -n "$(find -L "$source_dir" -maxdepth 1 -name '*.md' 2>/dev/null | head -1)" ]] && has_sources=true ;;
      skills)
        for d in "$source_dir"/*/; do
          [[ -d "$d" ]] && local dname=$(basename "$d") && \
            [[ "$dname" != "copilot" && "$dname" != "claude" && "$dname" != "codex" && "$dname" != "gemini" ]] && \
            has_sources=true && break
        done ;;
      mcp)
        [[ -n "$(find -L "$source_dir" -maxdepth 1 \( -name '*.json' -o -name '*.md' \) 2>/dev/null | head -1)" ]] && has_sources=true ;;
      hooks)
        [[ -n "$(find -L "$source_dir" -maxdepth 1 -type f 2>/dev/null | grep -v '^\.' | head -1)" ]] && has_sources=true ;;
    esac
    $has_sources || continue

    if $DRY_RUN; then
      info "[dry-run] Would build harness-specific $content_type for: $harnesses"
      python3 "$build_script" "$source_dir" --type "$content_type" --harness "$harnesses" --dry-run
    else
      python3 "$build_script" "$source_dir" --type "$content_type" --harness "$harnesses" --quiet
    fi
  done
}

# ═════════════════════════════════════════════════════════════
# COPILOT — symlink individual agent .md files
# ═════════════════════════════════════════════════════════════
sync_copilot() {
  echo ""
  echo -e "${BOLD}── Syncing to GitHub Copilot CLI ──${NC}"

  mkdir -p "$COPILOT_AGENTS_DIR"

  if $REFRESH; then
    info "Cleaning existing symlinks in $COPILOT_AGENTS_DIR"
    purge_symlinks_in "$COPILOT_AGENTS_DIR"
  fi

  local build_dir="$AGENTS_HOME/agents/copilot"
  local count=0
  for agent_file in "${RESOLVED_AGENTS[@]}"; do
    [[ -f "$agent_file" ]] || continue
    local basename
    basename=$(basename "$agent_file")
    local built_file="$build_dir/$basename"
    [[ -f "$built_file" ]] || continue
    make_link "$built_file" "$COPILOT_AGENTS_DIR/$basename"
    count=$((count + 1))
  done
  log "Copilot: symlinked $count agent files → $COPILOT_AGENTS_DIR/"

  sync_skills_to "$TARGET_ROOT/.copilot/skills" "copilot" "Copilot"
  sync_rules_to "$TARGET_ROOT/.copilot/instructions" "copilot" "Copilot"
  sync_workflows_to "$TARGET_ROOT/.copilot/workflows" "copilot" "Copilot"
  sync_hooks_to "$TARGET_ROOT/.copilot/hooks" "copilot" "Copilot"
  sync_mcp_to "copilot" "Copilot"
}

# ═════════════════════════════════════════════════════════════
# CODEX — symlink individual agent .md files
# ═════════════════════════════════════════════════════════════
sync_codex() {
  echo ""
  echo -e "${BOLD}── Syncing to OpenAI Codex CLI ──${NC}"

  mkdir -p "$CODEX_AGENTS_DIR"

  if $REFRESH; then
    info "Cleaning existing symlinks in $CODEX_AGENTS_DIR"
    purge_symlinks_in "$CODEX_AGENTS_DIR"
  fi

  local build_dir="$AGENTS_HOME/agents/codex"
  local count=0
  for agent_file in "${RESOLVED_AGENTS[@]}"; do
    [[ -f "$agent_file" ]] || continue
    local basename
    basename=$(basename "$agent_file")
    local built_file="$build_dir/$basename"
    [[ -f "$built_file" ]] || continue
    make_link "$built_file" "$CODEX_AGENTS_DIR/$basename"
    count=$((count + 1))
  done
  log "Codex: symlinked $count agent files → $CODEX_AGENTS_DIR/"

  sync_skills_to "$CODEX_DIR/skills" "codex" "Codex"
  sync_rules_to "$CODEX_DIR/instructions" "codex" "Codex"
  sync_workflows_to "$CODEX_DIR/workflows" "codex" "Codex"
  sync_hooks_to "$CODEX_DIR/hooks" "codex" "Codex"
  sync_mcp_to "codex" "Codex"
}

# ═════════════════════════════════════════════════════════════
# CLAUDE CODE — symlink individual agent .md files
# ═════════════════════════════════════════════════════════════
sync_claude() {
  echo ""
  echo -e "${BOLD}── Syncing to Claude Code ──${NC}"

  local claude_agents_dir="$CLAUDE_DIR/agents"
  mkdir -p "$claude_agents_dir"

  if $REFRESH; then
    info "Cleaning existing symlinks in $claude_agents_dir"
    purge_symlinks_in "$claude_agents_dir"
  fi

  local build_dir="$AGENTS_HOME/agents/claude"
  local count=0
  for agent_file in "${RESOLVED_AGENTS[@]}"; do
    [[ -f "$agent_file" ]] || continue
    local basename
    basename=$(basename "$agent_file")
    local built_file="$build_dir/$basename"
    [[ -f "$built_file" ]] || continue
    make_link "$built_file" "$claude_agents_dir/$basename"
    count=$((count + 1))
  done
  log "Claude: symlinked $count agent files → $claude_agents_dir/"

  sync_skills_to "$CLAUDE_DIR/skills" "claude" "Claude"
  sync_rules_to "$CLAUDE_DIR/rules" "claude" "Claude"
  sync_workflows_to "$CLAUDE_DIR/workflows" "claude" "Claude"
  sync_hooks_to "$CLAUDE_DIR/hooks" "claude" "Claude"
  sync_mcp_to "claude" "Claude"
}

# ═════════════════════════════════════════════════════════════
# GEMINI CLI — generate concatenated GEMINI.md
# ═════════════════════════════════════════════════════════════
sync_gemini() {
  echo ""
  echo -e "${BOLD}── Syncing to Gemini CLI ──${NC}"

  if [[ ! -d "$GEMINI_DIR" ]]; then
    warn "Gemini directory not found at $GEMINI_DIR — creating it"
    mkdir -p "$GEMINI_DIR"
  fi

  local output="$GEMINI_DIR/GEMINI.md"
  local marker="<!-- MANAGED BY ~/ai-management sync.sh — DO NOT EDIT MANUALLY -->"
  local build_dir="$AGENTS_HOME/agents/gemini"

  if $DRY_RUN; then
    info "[dry-run] Would generate $output"
    return
  fi

  {
    echo "$marker"
    echo ""
    echo "# Custom Instructions"
    echo ""
    echo "> Auto-generated from \`~/ai-management/agents/\` by \`sync.sh\`"
    echo "> Last synced: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo ""

    # ── Global rules ──
    if [[ ${#RESOLVED_RULES[@]} -gt 0 ]]; then
      local rules_build_dir="$AGENTS_HOME/rules/gemini"
      echo "## Global Rules"
      echo ""
      for rule_file in "${RESOLVED_RULES[@]}"; do
        [[ -f "$rule_file" ]] || continue
        local rule_basename
        rule_basename=$(basename "$rule_file")
        local built_rule="$rules_build_dir/$rule_basename"
        [[ -f "$built_rule" ]] && rule_file="$built_rule"
        echo "### $(basename "$rule_file" .md)"
        echo ""
        cat "$rule_file"
        echo ""
      done
      echo "---"
      echo ""
    fi

    # ── Agent definitions ──
    echo "## Available Agent Personas"
    echo ""
    echo "When asked to work as a specific agent or persona, adopt the matching instructions below."
    echo ""

    for agent_file in "${RESOLVED_AGENTS[@]}"; do
      [[ -f "$agent_file" ]] || continue
      local basename
      basename=$(basename "$agent_file")
      local built_file="$build_dir/$basename"
      [[ -f "$built_file" ]] || continue
      local name
      name=$(basename "$built_file" .md)
      echo "---"
      echo ""
      echo "### Agent: $name"
      echo ""
      cat "$built_file"
      echo ""
    done

    # ── Workflows ──
    if [[ ${#RESOLVED_WORKFLOWS[@]} -gt 0 ]]; then
      local wf_build_dir="$AGENTS_HOME/workflows/gemini"
      echo "---"
      echo ""
      echo "## Workflows"
      echo ""
      for wf_file in "${RESOLVED_WORKFLOWS[@]}"; do
        [[ -f "$wf_file" ]] || continue
        local wf_basename
        wf_basename=$(basename "$wf_file")
        local built_wf="$wf_build_dir/$wf_basename"
        [[ -f "$built_wf" ]] && wf_file="$built_wf"
        echo "### $(basename "$wf_file" .md)"
        echo ""
        cat "$wf_file"
        echo ""
      done
    fi

    # ── Skills (embedded — Gemini has no native skills directory) ──
    if [[ ${#RESOLVED_SKILLS[@]} -gt 0 ]]; then
      local skills_build_dir="$AGENTS_HOME/skills/gemini"
      local has_skills=false
      for skill_dir in "${RESOLVED_SKILLS[@]}"; do
        [[ -d "$skill_dir" ]] || continue
        local skill_name
        skill_name=$(basename "$skill_dir")
        local use_dir="$skill_dir"
        [[ -d "$skills_build_dir/$skill_name" ]] && use_dir="$skills_build_dir/$skill_name"
        local skill_md=""
        [[ -f "$use_dir/SKILL.md" ]] && skill_md="$use_dir/SKILL.md"
        [[ -f "$use_dir/skill.md" ]] && skill_md="$use_dir/skill.md"
        [[ -n "$skill_md" ]] || continue
        if ! $has_skills; then
          echo "---"
          echo ""
          echo "## Skills"
          echo ""
          echo "The following skills are available. Use their instructions when relevant."
          echo ""
          has_skills=true
        fi
        echo "### Skill: $(basename "$skill_dir")"
        echo ""
        cat "$skill_md"
        echo ""
      done
    fi

  } > "$output"

  local size
  size=$(wc -c < "$output" | tr -d ' ')
  log "Gemini: generated $output ($(( size / 1024 ))KB)"

  sync_mcp_to "gemini" "Gemini"
}

# ═════════════════════════════════════════════════════════════
# PURGE — remove all managed files from target directories
# ═════════════════════════════════════════════════════════════
purge_copilot() {
  echo ""
  echo -e "${BOLD}── Purging Copilot ──${NC}"
  local dirs=(
    "$COPILOT_AGENTS_DIR"
    "$TARGET_ROOT/.copilot/skills"
    "$TARGET_ROOT/.copilot/instructions"
    "$TARGET_ROOT/.copilot/workflows"
    "$TARGET_ROOT/.copilot/hooks"
  )
  if $DRY_RUN; then
    for d in "${dirs[@]}"; do
      [[ -d "$d" ]] && info "[dry-run] Would purge symlinks in $d"
    done
    [[ -f "$TARGET_ROOT/.copilot/mcp.json" ]] && info "[dry-run] Would remove $TARGET_ROOT/.copilot/mcp.json"
    return
  fi
  for d in "${dirs[@]}"; do
    purge_symlinks_in "$d"
  done
  rm -f "$TARGET_ROOT/.copilot/mcp.json" 2>/dev/null || true
  log "Copilot: purged all managed files"
}

purge_codex() {
  echo ""
  echo -e "${BOLD}── Purging Codex ──${NC}"
  local dirs=(
    "$CODEX_AGENTS_DIR"
    "$CODEX_DIR/skills"
    "$CODEX_DIR/instructions"
    "$CODEX_DIR/workflows"
    "$CODEX_DIR/hooks"
  )
  if $DRY_RUN; then
    for d in "${dirs[@]}"; do
      [[ -d "$d" ]] && info "[dry-run] Would purge symlinks in $d"
    done
    [[ -f "$CODEX_DIR/mcp-servers.json" ]] && info "[dry-run] Would remove $CODEX_DIR/mcp-servers.json"
    return
  fi
  for d in "${dirs[@]}"; do
    purge_symlinks_in "$d"
  done
  rm -f "$CODEX_DIR/AGENTS.md" 2>/dev/null || true
  rm -f "$CODEX_DIR/mcp-servers.json" 2>/dev/null || true
  log "Codex: purged all managed files"
}

purge_claude() {
  echo ""
  echo -e "${BOLD}── Purging Claude ──${NC}"
  local dirs=(
    "$CLAUDE_DIR/agents"
    "$CLAUDE_DIR/skills"
    "$CLAUDE_DIR/rules"
    "$CLAUDE_DIR/workflows"
    "$CLAUDE_DIR/hooks"
  )
  if $DRY_RUN; then
    for d in "${dirs[@]}"; do
      [[ -d "$d" ]] && info "[dry-run] Would purge symlinks in $d"
    done
    [[ -f "$CLAUDE_DIR/mcp.json" ]] && info "[dry-run] Would remove $CLAUDE_DIR/mcp.json"
    return
  fi
  for d in "${dirs[@]}"; do
    purge_symlinks_in "$d"
  done
  rm -f "$CLAUDE_DIR/mcp.json" 2>/dev/null || true
  log "Claude: purged all managed files"
}

purge_gemini() {
  echo ""
  echo -e "${BOLD}── Purging Gemini ──${NC}"
  local output="$GEMINI_DIR/GEMINI.md"
  if [[ ! -f "$output" ]]; then
    info "Nothing to purge — $output does not exist"
    return
  fi
  if $DRY_RUN; then
    info "[dry-run] Would remove $output"
    return
  fi
  rm -f "$output"
  log "Gemini: purged $output"
}

# ═════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════
echo -e "${BOLD}🔄 AI Management Sync — $(date '+%Y-%m-%d %H:%M:%S')${NC}"
$DRY_RUN && echo -e "${YELLOW}(dry-run mode)${NC}"

# ── Restore mode ─────────────────────────────────────────────
if $RESTORE || $RESTORE_LATEST; then
  for target in "${TARGETS[@]}"; do
    restore_target "$target"
  done
  echo ""
  log "Restore complete."
  exit 0
fi

# ── Backup existing files before any changes ─────────────────
if $BACKUP; then
  echo ""
  echo -e "${BOLD}── Backing up existing managed files ──${NC}"
  for target in "${TARGETS[@]}"; do
    while IFS= read -r p; do
      [[ -n "$p" ]] && backup_path "$target" "$p"
    done < <(managed_paths_for "$target")
  done
fi

if $PURGE; then
  echo -e "${RED}(purge mode — removing all managed files from targets)${NC}"
  for target in "${TARGETS[@]}"; do
    case "$target" in
      copilot) purge_copilot ;;
      codex)   purge_codex ;;
      claude)  purge_claude ;;
      gemini)  purge_gemini ;;
    esac
  done
  if ! $REFRESH; then
    echo ""
    log "Purge complete."
    exit 0
  fi
  echo ""
  info "Continuing with fresh sync…"
fi

# ── Build harness-specific files for all content types ──
local_harnesses=$(IFS=,; echo "${TARGETS[*]}")
build_all "$local_harnesses"

for target in "${TARGETS[@]}"; do
  case "$target" in
    copilot) sync_copilot ;;
    codex)   sync_codex ;;
    claude)  sync_claude ;;
    gemini)  sync_gemini ;;
  esac
done

echo ""
log "Sync complete."
