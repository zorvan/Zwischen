# Failing Tests Analysis Report

## Test Name Summary

All 23 failing tests:

1. `tests/test_comprehensive.py::TestEventFlowHandlers::test_handle_join_event_not_found`
2. `tests/test_comprehensive.py::TestEventFlowHandlers::test_handle_join_event_locked`
3. `tests/test_comprehensive.py::TestEventFlowHandlers::test_handle_confirm_state_validation`
4. `tests/test_comprehensive.py::TestEventFlowHandlers::test_handle_lock_wrong_state`
5. `tests/test_comprehensive.py::TestEventPresenters::test_format_event_details_uses_normalized_participants`
6. `tests/test_comprehensive.py::TestConstraintsAvailability::test_organizer_can_add_private_availability`
7. `tests/test_comprehensive.py::TestEventCreation::test_create_event_with_valid_data`
8. `tests/test_err_txt_scenario.py::test_err_txt_scenario_insert_event_with_hashtags`
9. `tests/test_err_txt_scenario.py::test_err_txt_scenario_query_events_with_hashtags`
10. `tests/test_err_txt_scenario.py::test_err_txt_scenario_scheduler_job`
11. `tests/test_err_txt_scenario.py::test_err_txt_scenario_update_event_hashtags`
12. `tests/test_schema_consistency.py::test_event_lifecycle_with_hashtags`
13. `tests/test_services.py::TestEventLifecycleService::test_transition_with_lifecycle_completed`
14. `tests/integration/test_event_model_lifecycle.py::test_event_full_lifecycle_with_hashtags`
15. `tests/integration/test_event_model_lifecycle.py::test_event_live_card_creation`
16. `tests/integration/test_event_model_lifecycle.py::test_event_memory_with_lineage`
17. `tests/integration/test_event_model_lifecycle.py::test_event_participant_with_status`
18. `tests/integration/test_event_model_lifecycle.py::test_event_waitlist`
19. `tests/integration/commands/test_availability_flow.py::test_availability_flow_complete_save`
20. `tests/scenarios/test_event_journey_simulator.py::test_scenario_simulator_supports_full_event_journey`
21. `tests/scenarios/test_event_journey_simulator.py::test_ultimate_chat_style_multi_attempts_build_failure_then_memory`
22. `tests/scenarios/test_event_journey_simulator.py::test_modify_uncommit_and_reconfirm_are_modeled_in_simulator`
23. `tests/scenarios/test_event_journey_simulator.py::test_waitlist_decline_rolls_forward_to_next_candidate`

---

## Detailed Analysis

### Critical (7 tests)

#### 1. `test_handle_join_event_not_found`, `test_handle_join_event_locked`, `test_handle_confirm_state_validation`, `test_handle_lock_wrong_state` (4 tests)

**Root Cause:** API signature mismatch  
**File:** `bot/handlers/event_flow.py:91`, `bot/handlers/event_flow.py:440`, `bot/handlers/event_flow.py:810`

**Error:** `TypeError: object MagicMock can't be used in 'await' expression`

**Issue:** The `query.answer()` method is being called as an async method (with `await`), but in tests it's mocked as a regular `MagicMock` object. The method needs to be async-aware or the mock needs to be configured as async.

**Location:** `bot/handlers/event_flow.py` lines 91, 440, 810 use `await query.answer(...)`

**Category:** Critical  
**Recommended Action:** Update test mocks to properly handle async methods  
**Priority:** High - breaks core event flow handler tests

---

#### 2. `test_create_event_with_valid_data` (1 test)

**Root Cause:** Missing function  
**File:** `bot/commands/event_creation.py:29-46`, `tests/test_comprehensive.py:584`

**Error:** `ImportError: cannot import name 'start_event_flow' from 'bot.commands.event_creation'`

**Issue:** The test imports `start_event_flow` but the module only exports `start_event_flow_from_prefill`. The function name is different between the test expectation and the actual implementation.

**Root Cause:** Function `start_event_flow` doesn't exist; only `start_event_flow_from_prefill` is available

**Category:** Critical  
**Recommended Action:** Update test to use correct function name `start_event_flow_from_prefill`  
**Priority:** High - breaks event creation test

---

#### 3. `test_event_lifecycle_with_hashtags`, `test_err_txt_scenario_insert_event_with_hashtags`, `test_err_txt_scenario_query_events_with_hashtags`, `test_err_txt_scenario_scheduler_job`, `test_err_txt_scenario_update_event_hashtags`, `test_event_full_lifecycle_with_hashtags`, `test_event_live_card_creation`, `test_event_memory_with_lineage`, `test_event_participant_with_status`, `test_event_waitlist`, `test_scenario_simulator_supports_full_event_journey`, `test_ultimate_chat_style_multi_attempts_build_failure_then_memory`, `test_modify_uncommit_and_reconfirm_are_modeled_in_simulator`, `test_waitlist_decline_rolls_forward_to_next_candidate` (14 tests total)

**Root Cause:** Database schema issues  
**Files:** Multiple database tests

**Error:** `sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) NOT NULL constraint failed: events.event_id`  
Or: `sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) NOT NULL constraint failed: groups.group_id`

**Issue:** Tests are trying to insert records without properly setting the primary key (`event_id` or `group_id`). The auto-increment is not working as expected, likely because:

1. Tests are directly inserting into the database without using the proper session/persistence layer
2. The `event_id` field is not configured as auto-increment
3. Tests are bypassing ORM methods that normally set these values

**Category:** Critical  
**Recommended Action:** Update tests to use proper session/ORM methods that handle auto-increment IDs  
**Priority:** High - breaks all database integration tests

---

### High (2 tests)

#### 4. `test_transition_with_lifecycle_completed`

**Root Cause:** Logic error  
**File:** `tests/test_services.py::TestEventLifecycleService::test_transition_with_lifecycle_completed`

**Error:** Test failure in event lifecycle transition validation

**Issue:** Test expects a certain transition behavior when lifecycle is completed, but the implementation may have changed or the test expectations are outdated.

**Category:** High  
**Recommended Action:** Review test expectations vs actual implementation logic  
**Priority:** Medium - important feature validation

---

#### 5. `test_availability_flow_complete_save`

**Root Cause:** Logic error / API change  
**File:** `tests/integration/commands/test_availability_flow.py:224`

**Error:** `AssertionError: assert 'Availability saved' in '❌ Event not found.'`

**Issue:** The test expects "Availability saved" message but gets "❌ Event not found." This suggests either:
- Event creation in the test setup is incomplete
- The availability flow is looking for events by different criteria than expected
- Test data is not being persisted correctly

**Category:** High  
**Recommended Action:** Update test setup to properly create events before testing availability flow  
**Priority:** Medium - important feature validation

---

### Medium (1 test)

#### 6. `test_format_event_details_uses_normalized_participants`

**Root Cause:** Logic error / API change  
**File:** `tests/test_comprehensive.py::TestEventPresenters::test_format_event_details_uses_normalized_participants:290`

**Error:** `AssertionError: assert 'Attendees (2):' in '📋 *Event 77 Details*...'`

**Issue:** The test expects "Attendees (2):" in the formatted output, but the actual output shows "Attendees (3):" (User101, User102, User103). The test may have incorrect expectations about which participants should be included or the normalization logic has changed.

**Category:** Medium  
**Recommended Action:** Update test to reflect correct expected behavior or verify normalization logic  
**Priority:** Low - presentation/formatting issue

---

### Low (1 test)

#### 7. `test_organizer_can_add_private_availability`

**Root Cause:** Import/scope error  
**File:** `bot/commands/constraints.py:686`

**Error:** `UnboundLocalError: cannot access local variable 'select' where it is not associated with a value`

**Issue:** There's a local variable `select` being referenced but never defined in the function scope. This is likely:
- A missing import statement
- A typo (maybe `select` should be a different variable name)
- A variable that was removed but not cleaned up

**Category:** Low  
**Recommended Action:** Fix the UnboundLocalError by proper variable initialization/import  
**Priority:** Low - edge case constraint handling

---

## Summary by Category

| Category | Count | Tests Affected |
|----------|-------|----------------|
| Critical | 7 | Tests with broken core functionality |
| High | 2 | Important features not working |
| Medium | 1 | Edge cases, presentation issues |
| Low | 1 | Minor issues |

## Recommended Actions by Category

### Critical (7 tests) - **Fix Implementation/Tests Immediately**

| Test Group | Action | Priority |
|------------|--------|----------|
| Event flow handlers (4 tests) | Update mocks to be async-aware or fix `query.answer()` implementation | High |
| Event creation (1 test) | Update test to use `start_event_flow_from_prefill` instead of `start_event_flow` | High |
| Database schema (14 tests) | Fix auto-increment ID handling, ensure proper ORM usage | High |

### High (2 tests) - **Review and Fix**

| Test Group | Action | Priority |
|------------|--------|----------|
| Lifecycle transitions (1 test) | Validate implementation vs test expectations | Medium |
| Availability flow (1 test) | Fix test setup to properly persist events | Medium |

### Medium/Low (2 tests) - **Nice to Fix**

| Test Group | Action | Priority |
|------------|--------|----------|
| Event formatting (1 test) | Update expectations or fix normalization logic | Low |
| Availability constraints (1 test) | Fix UnboundLocalError for `select` variable | Low |

---

## Root Cause Summary

1. **Async Mock Issue:** 4 tests fail because `MagicMock` doesn't handle async methods properly
2. **Missing Function:** 1 test imports non-existent function `start_event_flow`
3. **Database ID Issues:** 14 tests fail due to missing auto-increment or improper ID handling
4. **Logic Mismatches:** 3 tests have outdated expectations vs current implementation
5. **Scope/Import Errors:** 1 test has undefined variable issue

---

## Immediate Actions Required

**Fix in priority order:**

1. **Fix async mocks in event_flow tests** - Update all tests that mock Telegram update objects to properly handle async methods
2. **Fix function name import** - Change `start_event_flow` to `start_event_flow_from_prefill` in test
3. **Fix database auto-increment** - Ensure tests use proper ORM methods or fix schema
4. **Review implementation changes** - Compare tests with actual code to identify logic mismatches
5. **Fix UnboundLocalError** - Add missing import or fix variable scope

---

*Report generated: 2026-04-17*
