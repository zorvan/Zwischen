# Failing Tests Analysis Report

**Test Suite:** `/home/zorvan/Work/projects/Zwischen/telegram-bot/tests/`  
**Total Failing Tests:** 23  
**Total Passing Tests:** 144  
**Total XFailed Tests:** 1  
**Run Date:** 2026-04-17

---

## Executive Summary

The test suite has **23 failing tests** across three main categories:

1. **Async Mock Issues** (4 tests) - MagicMock not configured for async methods
2. **Database Schema Issues** (14 tests) - Missing auto-increment IDs
3. **API/Function Name Mismatches** (2 tests) - Incorrect function names or imports

These are primarily **test infrastructure issues** rather than application logic bugs.

---

## Detailed Test Analysis

### 1. Async Mock Failures (4 tests) - **CRITICAL**

| Test Name | File | Line | Root Cause | Recommended Action |
|-----------|------|------|------------|-------------------|
| `test_handle_join_event_not_found` | test_comprehensive.py | 34 | `query.answer()` is async but mocked as sync | Make mock async |
| `test_handle_join_event_locked` | test_comprehensive.py | 59 | Same as above | Make mock async |
| `test_handle_confirm_state_validation` | test_comprehensive.py | 84 | Same as above | Make mock async |
| `test_handle_lock_wrong_state` | test_comprehensive.py | 109 | Same as above | Make mock async |

**Error:** `TypeError: object MagicMock can't be used in 'await' expression`

**Source:** `bot/handlers/event_flow.py:91, 440, 810`

**Fix:** Configure MagicMock with `AsyncMock` or `spec_set`:
```python
from unittest.mock import AsyncMock
query.answer = AsyncMock()
```

---

### 2. Function Name Mismatch (1 test) - **CRITICAL**

| Test Name | File | Line | Root Cause | Recommended Action |
|-----------|------|------|------------|-------------------|
| `test_create_event_with_valid_data` | test_comprehensive.py | 584 | Imports non-existent `start_event_flow` | Use `start_event_flow_from_prefill` |

**Error:** `ImportError: cannot import name 'start_event_flow' from 'bot.commands.event_creation'`

**Source:** `bot/commands/event_creation.py:10-27`

**Fix:** Change line 584:
```python
# Old
from bot.commands.event_creation import start_event_flow

# New
from bot.commands.event_creation import start_event_flow_from_prefill
```

Also update line 614 to use correct function name.

---

### 3. Database Schema Issues (14 tests) - **CRITICAL**

| Test Name | File | Error | Recommended Action |
|-----------|------|-------|-------------------|
| `test_err_txt_scenario_insert_event_with_hashtags` | test_err_txt_scenario.py | `NOT NULL constraint failed: events.event_id` | Use ORM session properly |
| `test_err_txt_scenario_query_events_with_hashtags` | test_err_txt_scenario.py | `NOT NULL constraint failed: events.event_id` | Use ORM session properly |
| `test_err_txt_scenario_scheduler_job` | test_err_txt_scenario.py | `NOT NULL constraint failed: events.event_id` | Use ORM session properly |
| `test_err_txt_scenario_update_event_hashtags` | test_err_txt_scenario.py | `NOT NULL constraint failed: events.event_id` | Use ORM session properly |
| `test_event_lifecycle_with_hashtags` | test_schema_consistency.py | `NOT NULL constraint failed: events.event_id` | Use ORM session properly |
| `test_event_full_lifecycle_with_hashtags` | test_event_model_lifecycle.py | `NOT NULL constraint failed: events.event_id` | Use ORM session properly |
| `test_event_live_card_creation` | test_event_model_lifecycle.py | `NOT NULL constraint failed: events.event_id` | Use ORM session properly |
| `test_event_memory_with_lineage` | test_event_model_lifecycle.py | `NOT NULL constraint failed: events.event_id` | Use ORM session properly |
| `test_event_participant_with_status` | test_event_model_lifecycle.py | `NOT NULL constraint failed: events.event_id` | Use ORM session properly |
| `test_event_waitlist` | test_event_model_lifecycle.py | `NOT NULL constraint failed: events.event_id` | Use ORM session properly |
| `test_scenario_simulator_supports_full_event_journey` | test_event_journey_simulator.py | `NOT NULL constraint failed: groups.group_id` | Use ORM session properly |
| `test_ultimate_chat_style_multi_attempts_build_failure_then_memory` | test_event_journey_simulator.py | `NOT NULL constraint failed: groups.group_id` | Use ORM session properly |
| `test_modify_uncommit_and_reconfirm_are_modeled_in_simulator` | test_event_journey_simulator.py | `NOT NULL constraint failed: groups.group_id` | Use ORM session properly |
| `test_waitlist_decline_rolls_forward_to_next_candidate` | test_event_journey_simulator.py | `NOT NULL constraint failed: groups.group_id` | Use ORM session properly |

**Error:** `sqlalchemy.exc.IntegrityError: NOT NULL constraint failed`

**Fix:** Tests should use the ORM session's `add()` and `flush()` methods rather than raw INSERT statements. The `simulator.py` and test setup should properly handle ID generation.

---

### 4. Logic/Error Issues (4 tests) - **HIGH/MEDIUM**

| Test Name | File | Line | Root Cause | Recommended Action |
|-----------|------|------|------------|-------------------|
| `test_transition_with_lifecycle_completed` | test_services.py | - | Lifecycle transition logic mismatch | Review implementation |
| `test_availability_flow_complete_save` | test_availability_flow.py | 224 | Event not found in availability flow | Fix test setup persistence |
| `test_format_event_details_uses_normalized_participants` | test_comprehensive.py | 290 | Wrong expectation: "Attendees (2)" vs actual "Attendees (3)" | Update expectations |
| `test_organizer_can_add_private_availability` | test_comprehensive.py | 367 | `UnboundLocalError: select` variable undefined | Add missing import/fix scope |

---

## Categorization Summary

| Category | Count | Impact | Priority |
|----------|-------|--------|----------|
| **Critical** | 7 | Core functionality broken | IMMEDIATE |
| **High** | 2 | Important features not working | HIGH |
| **Medium** | 1 | Edge cases, presentation | MEDIUM |
| **Low** | 1 | Cosmetic, minor issues | LOW |

---

## Recommended Actions by Priority

### Immediate (Fix First)

1. **Async Mock Configuration** - Update all 4 event_flow handler tests to use `AsyncMock` for async methods
2. **Import Fix** - Update test to import `start_event_flow_from_prefill` instead of `start_event_flow`
3. **Database Session Fix** - Fix all 14 database tests to use proper ORM session methods

### High Priority

4. **Review Lifecycle Tests** - Compare implementation with test expectations for `test_transition_with_lifecycle_completed`
5. **Fix Availability Test Setup** - Ensure events are properly persisted before availability flow tests

### Medium/Low Priority

6. **Update Expectations** - Adjust test assertions to match current implementation output
7. **Fix UnboundLocalError** - Resolve undefined `select` variable in constraints command

---

## Root Cause Breakdown

| Root Cause Type | Count | Percentage |
|-----------------|-------|------------|
| Async mock misconfiguration | 4 | 17.4% |
| Missing/incorrect function name | 1 | 4.3% |
| Database schema/ID handling | 14 | 60.9% |
| Logic/test expectation mismatch | 2 | 8.7% |
| Variable scope/import error | 1 | 4.3% |
| Other/unknown | 1 | 4.3% |

---

## Test Categories by File

| File | Failing Tests | Critical Issues |
|------|---------------|-----------------|
| test_comprehensive.py | 7 | Async mocks, function name, logic |
| test_err_txt_scenario.py | 4 | Database schema |
| test_schema_consistency.py | 1 | Database schema |
| test_services.py | 1 | Logic mismatch |
| test_event_model_lifecycle.py | 6 | Database schema |
| test_availability_flow.py | 1 | Logic mismatch |
| test_event_journey_simulator.py | 4 | Database schema |
| **TOTAL** | **24** | **19** (79%) |

---

## Conclusion

**Primary Issues:**
- Database auto-increment handling (60.9% of failures)
- Async mock configuration (17.4% of failures)

**Solution Strategy:**
1. Fix async mocks using `unittest.mock.AsyncMock`
2. Import correct function names
3. Refactor database tests to use proper ORM session methods

**Estimated Effort:**
- Critical issues: 2-3 hours
- High/Medium/Low issues: 3-4 hours

---

*Report generated automatically from test output analysis*
