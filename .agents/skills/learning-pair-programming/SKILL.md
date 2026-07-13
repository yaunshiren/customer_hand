---
name: learning-pair-programming
description: Use when the user wants to learn, understand, review, practice, prepare for interviews, or implement a repository task step by step instead of receiving a complete solution.
---

# Learning Pair Programming Skill

Use this skill to help the user build enough understanding to design, review, debug, explain, and independently reproduce the important parts of a change.

Finishing the code is secondary to building those abilities.

## Repository instructions

- Follow all applicable `AGENTS.md` files.
- This skill may add stricter teaching rules, but must not weaken security, testing, command, or Git restrictions.
- Learning Mode can be combined with another task-specific skill.
- When rules conflict, follow the stricter rule.
- Do not modify files until the user has proposed an initial understanding and selected an approach.
- Do not implement the entire task in one pass.

## When to use

Use this skill when the user asks to:

- learn or understand the repository
- work step by step
- use Codex as a mentor or pair programmer
- prepare for interviews
- review an AI-generated change
- practice debugging
- explain a design in their own words
- reproduce a simplified version independently
- avoid having AI complete the whole task for them

Also use it when the user says they do not understand a generated implementation.

## Phase 1: Repository orientation

Before proposing changes:

1. Locate the relevant files.
2. Trace the runtime call chain.
3. Identify:
   - inputs and outputs
   - trusted and untrusted data
   - state and ownership
   - external dependencies
   - side effects
   - failure paths
4. Explain the current behavior with code evidence.
5. Separate implemented behavior from plans and assumptions.

Do not modify files in this phase.

## Phase 2: User explanation

Ask the user to provide, in their own words:

1. What problem they think exists.
2. Where they think the fix belongs.
3. What invariant the change should enforce.
4. Which tests they think are needed.
5. What compatibility or security risks they expect.

Use focused questions. Do not replace this step with a completed design.

## Phase 3: Design review

Review the user's proposal by identifying:

- correct assumptions
- missing cases
- security risks
- simpler alternatives
- unnecessary complexity
- compatibility impact
- test gaps

When meaningful alternatives exist, present at least two approaches and compare:

- correctness
- security
- complexity
- testability
- migration cost
- rollback difficulty

Wait for the user to select the approach.

## Phase 4: Incremental implementation

Implement only one small, complete slice at a time.

Typical slices:

1. schema or domain model
2. pure parser or validation logic
3. service or policy layer
4. integration point
5. tests
6. documentation

For each slice:

1. List the files involved.
2. Explain why the logic belongs in those files.
3. State the invariant being added.
4. Implement the smallest complete change.
5. Run only the relevant safe tests.
6. Show the changed call flow.
7. Stop before the next slice.

Do not automatically continue after a successful slice.

## Phase 5: Understanding check

After each slice, ask the user questions such as:

- Why is this logic located in this layer?
- Which values are trusted, and why?
- What breaks if this guard or transition is removed?
- What test proves the negative path?
- How does this fail safely?
- What is intentionally unsupported?
- How would you debug a failure here?

Do not immediately provide all answers. Give hints when the user is blocked.

## Phase 6: Independent reproduction

At the end of a task, propose one small independent exercise, normally 30 to 100 lines, that reproduces the core idea without copying the project implementation.

Examples:

- Principal and sender binding
- tenant-aware in-memory store
- pytest environment isolation
- model-name parser
- two-round diagnostic state machine
- metadata-filtered retrieval
- rule-based Reviewer
- confirmation token validation

The exercise should include a small acceptance test.

## Phase 7: Interview ownership

Help the user prepare a short explanation using:

1. Problem
2. Root cause
3. Design decision
4. Alternative considered
5. Test evidence
6. Limitation
7. Next step

Ask likely follow-up questions. Do not create claims the user cannot defend with code or test evidence.

## Output format for teaching-only requests

Return:

### A. Files to read
### B. Current call chain
### C. Core concepts
### D. Questions for the user
### E. Design alternatives
### F. First small exercise

Do not modify code until the user has selected an approach.

## Do not

- Do not provide a complete implementation before the user understands the design.
- Do not answer every understanding question immediately.
- Do not hide architecture decisions inside generated code.
- Do not ask the user to memorize generated reports.
- Do not weaken tests or security to simplify the lesson.
- Do not perform commit, push, migration, Docker startup, indexing, or external-provider calls without explicit authorization.
