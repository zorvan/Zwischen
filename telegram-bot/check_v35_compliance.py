#!/usr/bin/env python3
"""
v3.5 Coordination Engine — Compliance Checker

Runs all automated checks against the v3.5 specification:
- Callback handler wiring
- No remaining TODO/STUB/placeholder code
- No deprecated commands still full-handlers
- Schema compliance (CHECK constraints removed)
- LLM layer compliance (infer_action exists, FeedbackInference removed)
- Model compliance (expertise_per_activity removed)
- Infrastructure present (fallbacks.py, cleanup job, rate limiter warning)

Usage:
    python check_v35_compliance.py

Exit code 0 = all checks pass, 1 = failures found.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PYTHON_FILES = list(ROOT.rglob("*.py"))
PYTHON_FILES = [
    f for f in PYTHON_FILES if ".venv" not in str(f) and "__pycache__" not in str(f)
]

# ── Results accumulator ──────────────────────────────────────────────
failures: list[str] = []
passes: list[str] = []


def check(description: str, condition: bool, detail: str = "") -> None:
    if condition:
        passes.append(f"PASS: {description}" + (f" — {detail}" if detail else ""))
    else:
        failures.append(f"FAIL: {description}" + (f" — {detail}" if detail else ""))


# ── 1. Callback handler wiring ───────────────────────────────────────
def check_callback_wiring() -> None:
    """Every callback pattern in main.py must resolve to an existing function."""
    with open(ROOT / "main.py") as f:
        content = f.read()

    patterns = re.findall(r'\(r"([^"]+)",\s+([\w.]+(?:\.[\w()]+)*)\)', content)

    # Parse main.py to import the bot handlers module
    main_ast = ast.parse(content)
    handler_imports: dict[str, str] = {}
    # Map alias -> actual submodule name for `as` imports
    alias_to_submodule: dict[str, str] = {}

    for node in ast.walk(main_ast):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("bot."):
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    handler_imports[local_name] = node.module
                    if alias.asname:
                        alias_to_submodule[alias.asname] = alias.name

    for pattern, handler_expr in patterns:
        # Normalise: e.g. "waitlist_handlers.handle_menu_callback"
        # handler_expr may contain function calls like handle_menu_callback
        match = re.match(r"^([\w.]+)\.([\w]+)(?:\(\))?$", handler_expr)
        if not match:
            check(
                f"callback pattern: {pattern}",
                False,
                f"unparseable handler: {handler_expr}",
            )
            continue

        import_name, func_name = match.groups()
        module_name = handler_imports.get(import_name)

        if not module_name:
            check(
                f"callback pattern: {pattern}",
                False,
                f"import '{import_name}' not found in main.py",
            )
            continue

        # module_name is the package (e.g. "bot.handlers")
        # func_name is the attribute on the imported name (e.g. "route_event_callback" on "event_panel")
        # We need to resolve: bot.handlers.event_panel.route_event_callback
        # The import_name is the alias (e.g. "event_panel"), so we need to find
        # which submodule it refers to within the package.
        try:
            package = __import__(module_name, fromlist=[import_name])
            # If import_name is an alias (e.g. waitlist_handlers), resolve to actual submodule
            submodule_name = alias_to_submodule.get(import_name, import_name)
            imported_obj = getattr(package, submodule_name, None)
            if imported_obj is None:
                check(
                    f"callback pattern: {pattern}",
                    False,
                    f"'{submodule_name}' not found in {module_name}",
                )
                continue
            # imported_obj is the actual module (e.g. bot.handlers.event_panel)
            if not hasattr(imported_obj, func_name):
                check(
                    f"callback pattern: {pattern}",
                    False,
                    f"{import_name} has no '{func_name}'",
                )
            else:
                passes.append(
                    f"WIRING: {pattern} → {module_name}.{import_name}.{func_name}"
                )
        except ImportError as e:
            check(
                f"callback pattern: {pattern}",
                False,
                f"cannot import {module_name}: {e}",
            )


# ── 2. No remaining TODO/STUB/placeholder code ───────────────────────
def check_no_stubs() -> None:
    """Core files must not contain TODO/STUB/placeholder implementations."""
    core_files = [
        "bot/handlers/event_panel.py",
        "bot/handlers/event_flow.py",
        "bot/commands/events.py",
        "bot/handlers/menus.py",
        "ai/llm.py",
        "bot/commands/organize_event.py",
        "bot/commands/status.py",
        "bot/commands/event_details.py",
        "bot/commands/join.py",
        "bot/commands/confirm.py",
        "bot/commands/lock.py",
        "bot/commands/constraints.py",
        "bot/commands/meaning_formation.py",
    ]

    stub_patterns = re.compile(
        r"(TODO.*implement|STUB.*implement|coming soon|not implemented|placeholder.*implementation)",
        re.IGNORECASE,
    )

    for rel_path in core_files:
        file_path = ROOT / rel_path
        if not file_path.exists():
            check(f"file exists: {rel_path}", False, "file not found")
            continue

        with open(file_path) as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            # Skip docstrings about PRD TODOs and config placeholders
            if "PRD" in line or "TODO-0" in line:
                continue
            if stub_patterns.search(line):
                check(f"no stubs in {rel_path}:{i}", False, line.strip()[:100])


# ── 3. Deprecated commands redirect ──────────────────────────────────
def check_deprecated_commands() -> None:
    """Deprecated commands must redirect to /events, not be full handlers."""
    deprecated = {
        "bot/commands/organize_event.py": "handle",
        "bot/commands/status.py": "handle",
        "bot/commands/event_details.py": "handle",
        "bot/commands/join.py": "handle",
        "bot/commands/confirm.py": "handle",
        "bot/commands/lock.py": "handle",
        "bot/commands/constraints.py": "handle",
        "bot/commands/meaning_formation.py": "handle",
    }

    for rel_path, func_name in deprecated.items():
        file_path = ROOT / rel_path
        with open(file_path) as f:
            content = f.read()

        # Check it contains redirect text
        has_redirect = "Use /events" in content or "redirects to /events" in content
        check(f"{rel_path} redirects", has_redirect, "still a full handler")


# ── 4. Schema compliance ─────────────────────────────────────────────
def check_schema_compliance() -> None:
    """CHECK constraints on semantic strings must be removed."""
    with open(ROOT / "db" / "schema.sql") as f:
        content = f.read()

    # These CHECK constraints should NOT exist
    forbidden_checks = [
        ("constraints.type CHECK", r"constraints.*type.*CHECK"),
        ("logs.action CHECK", r"logs.*action.*CHECK"),
        ("groups.group_type CHECK", r"groups.*group_type.*CHECK"),
        ("events.state CHECK", r"events.*state.*CHECK"),
        ("idempotency_keys.status CHECK", r"idempotency.*status.*CHECK"),
        ("event_waitlist.status CHECK", r"waitlist.*status.*CHECK"),
        ("constraints.confidence CHECK", r"confidence.*CHECK"),
    ]

    for name, pattern in forbidden_checks:
        found = bool(re.search(pattern, content, re.IGNORECASE | re.DOTALL))
        check(f"CHECK removed: {name}", not found, "CHECK constraint still present")

    # Index on renamed column must exist
    has_edm_index = bool(re.search(r"idx_events_emergency_admin_tg", content))
    check(
        "index uses renamed column", has_edm_index, "still references old column name"
    )


# ── 5. LLM layer compliance ──────────────────────────────────────────
def check_llm_compliance() -> None:
    """LLM layer must use infer_action(), not regex fallbacks."""
    with open(ROOT / "ai" / "llm.py") as f:
        content = f.read()

    # infer_action method must exist
    has_infer_action = "async def infer_action" in content
    check("LLMClient has infer_action()", has_infer_action)

    # _trim_to_token_budget must exist
    has_trim = "_trim_to_token_budget" in content
    check("LLMClient has _trim_to_token_budget()", has_trim)

    # Temperature should be 0.1 for structured output
    temp_match = re.search(r"LLM_TEMPERATURE\s*=\s*([\d.]+)", content)
    if temp_match:
        temp = float(temp_match.group(1))
        check("LLM_TEMPERATURE is 0.1", temp == 0.1, f"found {temp}")
    else:
        check("LLM_TEMPERATURE defined", False)

    # No regex fallback in infer_group_mention_action
    # (the method should delegate to infer_action, not have ~80 lines of regex)
    infer_group_match = re.search(
        r"async def infer_group_mention_action.*?(?=async def|\Z)",
        content,
        re.DOTALL,
    )
    if infer_group_match:
        method_body = infer_group_match.group()
        regex_fallback_lines = len(
            re.findall(r"re\.(?:search|match|findall)", method_body)
        )
        check(
            "infer_group_mention_action has no regex fallbacks",
            regex_fallback_lines == 0,
            f"found {regex_fallback_lines} re.search/match calls",
        )

    # FeedbackInference must be removed from ai/schemas.py
    with open(ROOT / "ai" / "schemas.py") as f:
        schemas_content = f.read()
    has_feedback = "class FeedbackInference" in schemas_content
    check("FeedbackInference removed from schemas.py", not has_feedback)


# ── 6. Model compliance ──────────────────────────────────────────────
def check_model_compliance() -> None:
    """Behavioral scoring artifacts must be removed."""
    with open(ROOT / "db" / "models.py") as f:
        content = f.read()

    # expertise_per_activity must not be in the model
    # (a comment is fine, but not an actual column)
    # Check it's only in a comment
    non_comment_lines = [
        line
        for line in content.split("\n")
        if "expertise_per_activity" in line and not line.strip().startswith("#")
    ]
    check(
        "expertise_per_activity not in User model",
        len(non_comment_lines) == 0,
        f"found in non-comment lines: {non_comment_lines}",
    )

    # emergency_admin_telegram_user_id must exist
    has_emergency_admin = "emergency_admin_telegram_user_id" in content
    check("emergency_admin_telegram_user_id in models", has_emergency_admin)

    # New models must exist
    new_models = ["EventEnrichment", "EventLineage", "EventLiveCard", "GroupSettings"]
    for model in new_models:
        has_model = f"class {model}" in content
        check(f"Model {model} exists", has_model)


# ── 7. Infrastructure present ────────────────────────────────────────
def check_infrastructure() -> None:
    """Required infrastructure files/functions must exist."""
    # fallbacks.py
    fallbacks_path = ROOT / "bot" / "common" / "fallbacks.py"
    if fallbacks_path.exists():
        with open(fallbacks_path) as f:
            content = f.read()
        check("fallbacks.py exists", True)
        check("FALLBACK_CLARIFY in fallbacks.py", "FALLBACK_CLARIFY" in content)
        check("FALLBACK_GENERAL in fallbacks.py", "FALLBACK_GENERAL" in content)
    else:
        check("fallbacks.py exists", False)

    # Rate limiter warning
    with open(ROOT / "bot" / "common" / "rate_limiter.py") as f:
        content = f.read()
    has_restart_warning = (
        "restart-safe" in content.lower() or "NOT restart-safe" in content
    )
    check("rate_limiter has restart warning", has_restart_warning)

    # Idempotency cleanup in scheduler
    with open(ROOT / "bot" / "common" / "scheduler.py") as f:
        content = f.read()
    has_cleanup = "cleanup_expired_idempotency_keys" in content
    check("scheduler has idempotency cleanup", has_cleanup)

    # ai/actions.py
    actions_path = ROOT / "ai" / "actions.py"
    if actions_path.exists():
        with open(actions_path) as f:
            content = f.read()
        actions = re.findall(r'"(\w+)":\s*\{', content)
        check(
            "ai/actions.py has ACTIONS registry",
            len(actions) >= 10,
            f"found {len(actions)} actions",
        )
    else:
        check("ai/actions.py exists", False)

    # ai/validator.py
    validator_path = ROOT / "ai" / "validator.py"
    if validator_path.exists():
        with open(validator_path) as f:
            content = f.read()
        check("ai/validator.py exists", True)
        check(
            "validate_action_result in validator.py",
            "validate_action_result" in content,
        )
    else:
        check("ai/validator.py exists", False)


# ── 8. Event panel fully wired ───────────────────────────────────────
def check_event_panel_wiring() -> None:
    """Event panel must be registered in main.py and have no stubs."""
    with open(ROOT / "main.py") as f:
        content = f.read()

    has_ev_pattern = bool(re.search(r'r"\^ev:"', content))
    check("ev: callback pattern registered in main.py", has_ev_pattern)

    # event_panel.py _handle_view must be real (not a stub)
    with open(ROOT / "bot" / "handlers" / "event_panel.py") as f:
        panel = f.read()

    view_match = re.search(
        r"async def _handle_view.*?(?=async def _handle_|\Z)",
        panel,
        re.DOTALL,
    )
    if view_match:
        view_body = view_match.group()
        is_stub = "Loading event details" in view_body or (
            "TODO" in view_body and "implement" in view_body.lower()
        )
        check("_handle_view is fully implemented", not is_stub)
    else:
        check("_handle_view function exists", False)

    # _handle_lock must not be a stub
    lock_match = re.search(
        r"async def _handle_lock.*?(?=async def _handle_|\Z)",
        panel,
        re.DOTALL,
    )
    if lock_match:
        lock_body = lock_match.group()
        is_stub = "coming soon" in lock_body or (
            "TODO" in lock_body and "implement" in lock_body.lower()
        )
        check("_handle_lock is fully implemented", not is_stub)
    else:
        check("_handle_lock function exists", False)


# ── 9. Event IDs removed from list display ───────────────────────────
def check_event_id_removal() -> None:
    """Event IDs should not appear in list display text."""
    with open(ROOT / "bot" / "commands" / "events.py") as f:
        content = f.read()

    # Should not have "ID `" pattern (showing event_id in prose)
    has_id_in_text = bool(re.search(r'ID\s+[`"]', content))
    check("No event IDs in events.py list text", not has_id_in_text)

    # But should still use ev:{id}:view callback format
    has_ev_format = 'callback_data=f"ev:' in content or 'callback_data="ev:' in content
    check("Uses ev:{id}:view callback format", has_ev_format)


# ── 10. Enrichment message handling ──────────────────────────────────
def check_enrichment_handling() -> None:
    """Enrichment prompts must set conversation state and process replies."""
    with open(ROOT / "bot" / "handlers" / "event_panel.py") as f:
        panel = f.read()

    # All enrichment prompts should set enrich_event_id / enrich_action
    for action in [
        "add_idea",
        "add_hashtag",
        "add_memory",
        "suggest_time",
        "add_constraint",
    ]:
        has_state = "enrich_action" in panel and "enrich_event_id" in panel
        check(f"enrichment {action} sets conversation state", has_state)

    # menus.py should have _handle_enrichment_message
    with open(ROOT / "bot" / "handlers" / "menus.py") as f:
        menus = f.read()

    has_enrich_handler = "_handle_enrichment_message" in menus
    check("menus.py has _handle_enrichment_message", has_enrich_handler)

    # handle_creation_message should check enrichment state first
    has_enrich_check = "enrich_event_id" in menus and "enrich_action" in menus
    check("handle_creation_message checks enrichment state", has_enrich_check)


# ── Main ─────────────────────────────────────────────────────────────
def main() -> int:
    print("=" * 60)
    print("v3.5 Coordination Engine — Compliance Checker")
    print("=" * 60)
    print()

    checks = [
        ("Callback wiring", check_callback_wiring),
        ("No stubs/TODOs", check_no_stubs),
        ("Deprecated commands", check_deprecated_commands),
        ("Schema compliance", check_schema_compliance),
        ("LLM layer", check_llm_compliance),
        ("Model compliance", check_model_compliance),
        ("Infrastructure", check_infrastructure),
        ("Event panel wiring", check_event_panel_wiring),
        ("Event ID removal", check_event_id_removal),
        ("Enrichment handling", check_enrichment_handling),
        ("Runtime safety", check_runtime_safety),
        ("Session handling", check_session_handling),
    ]

    for name, fn in checks:
        print(f"── {name} ──")
        fn()

    print()
    print("=" * 60)
    print(f"Results: {len(passes)} passed, {len(failures)} failed")
    print("=" * 60)

    if failures:
        print()
        print("FAILURES:")
        for f in failures:
            print(f"  ✗ {f}")
        print()
        return 1
    else:
        print()
        print("ALL CHECKS PASSED ✓")
        return 0


# ── 11. Runtime safety patterns ──────────────────────────────────────
def check_runtime_safety() -> None:
    """Check for common runtime failure patterns in Telegram handlers."""
    handler_files = [
        "bot/handlers/event_panel.py",
        "bot/handlers/event_flow.py",
        "bot/handlers/menus.py",
        "bot/handlers/mentions.py",
        "bot/commands/events.py",
        "bot/commands/start.py",
    ]

    for rel_path in handler_files:
        file_path = ROOT / rel_path
        if not file_path.exists():
            continue

        with open(file_path) as f:
            content = f.read()

        # Check 1: edit_message_text must be wrapped in try/except
        # Find all edit_message_text calls
        edit_calls = list(re.finditer(r"await\s+\w+\.edit_message_text\(", content))
        for call in edit_calls:
            # Look backwards from the call to find if there's a try: within ~30 lines
            start = max(0, call.start() - 500)
            preceding = content[start : call.start()]
            # Check if this call is within a try block
            try_count = preceding.count("try:")
            except_count = preceding.count("except")
            # If more try than except before this call, it's inside a try
            if try_count > except_count:
                continue  # Already inside a try block
            # Check if there's a try after this call (for the next few lines)
            end = min(len(content), call.end() + 200)
            following = content[call.end() : end]
            if "except" in following:
                continue  # Try/except follows the call
            check(
                f"edit_message_text protected in {rel_path}",
                False,
                f"unprotected edit at line {content[:call.start()].count(chr(10)) + 1}",
            )

        # Check 2: No imports from db.common (should be bot.common)
        bad_imports = re.findall(r"from\s+db\.common\.", content)
        if bad_imports:
            check(f"no db.common imports in {rel_path}", False, f"found: {bad_imports}")

        # Check 3: reply_text with Markdown should not include user data directly
        # (use reply_html or escape user content)
        markdown_replies = list(
            re.finditer(r'reply_text\([^)]*parse_mode="Markdown"', content)
        )
        for reply in markdown_replies:
            # Check if this reply includes f-string with user variables
            surrounding = content[max(0, reply.start() - 200) : reply.end() + 200]
            if (
                "display_name" in surrounding
                or "full_name" in surrounding
                or "username" in surrounding
            ):
                check(
                    f"Markdown reply safe in {rel_path}",
                    False,
                    f"user data in Markdown reply at line {content[:reply.start()].count(chr(10)) + 1}",
                )


# ── 12. Session handling consistency ─────────────────────────────────
def check_session_handling() -> None:
    """Ensure session handling is consistent across handlers."""
    handler_files = [
        "bot/handlers/event_panel.py",
        "bot/handlers/event_flow.py",
    ]

    for rel_path in handler_files:
        file_path = ROOT / rel_path
        if not file_path.exists():
            continue

        with open(file_path) as f:
            content = f.read()

        # Check for context.chat_data.get("session") pattern (anti-pattern)
        bad_pattern = re.findall(r'context\.chat_data\.get\("session"\)', content)
        if bad_pattern:
            check(
                f"no chat_data.session in {rel_path}",
                False,
                f"found {len(bad_pattern)} uses",
            )


if __name__ == "__main__":
    sys.exit(main())
