# P3 Final Manual Acceptance

Use this checklist once the final automated suites are green. It is intentionally
an end-to-end user acceptance check, not another development-stage script.

## Preconditions

- Go control plane is running.
- Python runtime is running.
- React frontend is running.
- The same account can open a normal conversation, Project A, and Project B.
- Project A and Project B each have distinguishable Project Knowledge.

## A. Explicit long-term memory

1. In a normal conversation say: `记住：以后写 Go 代码时尽量和 Java 对比讲解。`
2. Open **长期记忆**.
3. Confirm one active user memory represents that preference.
4. Confirm it is not tied to a Project.

Expected: the preference is stored once as User-global Memory.

## B. Cross-Project recall

1. Open Project A and ask a coding question without restating the preference.
2. Open Project B and ask another coding question.

Expected: both conversations may use the same user preference; no duplicate
Project-specific memory rows are created.

## C. Project Knowledge isolation

1. Put a unique fact only in Project A Knowledge.
2. Ask for it in Project A: it may be retrieved with Project evidence.
3. Ask for it in Project B: it must not be retrieved from Project A.
4. Open **长期记忆** and confirm the Project A fact was not automatically copied
   into User-global Memory.

Expected: Memory is global to the user; Knowledge remains Project-scoped.

## D. Current instruction overrides Memory

1. Keep a Memory such as `回答优先使用中文`.
2. In one request explicitly say: `这次只用英文回答。`

Expected: the current user instruction wins for that request without deleting or
silently rewriting the stored Memory.

## E. Manual correction authority

1. Open **长期记忆**.
2. Edit an automatically inferred memory.
3. Save it.

Expected: the corrected record becomes a manual/user-authoritative memory and a
later lower-authority inference cannot overwrite it.

## F. Forget / delete

1. Delete a test memory in **长期记忆**.
2. Start a new conversation and ask about that preference.

Expected: the deleted memory is no longer available for long-term retrieval.

## G. Run Details observability

1. Run a request that retrieves an existing Memory.
2. Run a request that writes or updates a Memory.
3. Open **Run Details → Memory** and **Run Details → Trace**.

Expected:

- `memory_retrieval` / `memory_write` metadata is visible;
- counts, keys, categories, scores/actions may be visible;
- full Memory content, password/token/secret text, and malformed raw Memory
  trace details are not exposed in the generic Trace view.

## H. Normal vs Project conversation boundary

Expected:

- User-global Memory can apply in both normal and Project conversations.
- `PROJECT_RUNTIME` appears only for Project conversations.
- Project Runtime bindings do not scope or duplicate User-global Memory.


### Forget epistemic-honesty check

After deleting the relevant long-term memory, open a fresh conversation and ask a memory-overview question such as `你还记得我对 Go 代码讲解有什么偏好吗？`. The expected answer must state that no relevant long-term memory is available. It must not invent a plausible preference from model priors, RAG, or Project Knowledge.
