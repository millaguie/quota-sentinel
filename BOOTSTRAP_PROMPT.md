You are bootstrapping **quota-sentinel** — an existing python project.

Agents configured: build, plan, ralph, pm, reviewer, explorer, test, sre, security, docs, refactor, devops
Security profile: moderate

There is EXISTING CODE in this project. Your job is to analyze it, understand
the user's priorities, and then configure the agent artifacts.

---

## Phase 1: Codebase Analysis

Read the project to understand what exists:
- Project structure: directories, entry points, config files
- Architecture: monolith, microservices, library, CLI, mobile app, etc.
- Build system and commands: build, test, lint, format, run
- Key frameworks and libraries in use
- Existing test patterns and coverage
- Code style and conventions already in place
- README and existing documentation

Present your analysis to the user as a brief structured summary.

---

## Phase 2: Intent Discovery

After presenting your analysis, ask the user (1-2 rounds):

**Round 1**:
- Is my analysis accurate? Anything important I'm missing?
- What are your priorities right now? What do you want to build, change, or improve?
- Are there areas of the codebase that need special attention from the agents?

**Round 2** (if needed):
- Clarify anything vague from the user's answers.
- Ask about any architectural decisions you noticed that seem incomplete or in flux.

Rules:
- Keep it brief — the codebase already provides most context.
- 2 rounds max. The user is here to work, not to be interviewed.
- If the user says "just configure it", skip to Phase 3.

---

## Phase 3: Confirmation

Present a summary combining your codebase analysis with the user's stated priorities:

```
PROJECT: [name]
DESCRIPTION: [what it does, based on code + user input]
ARCHITECTURE: [what you observed]
TECH STACK: [detected]

PRIORITIES:
  1. [what the user wants to work on]
  2. [...]

AGENT FOCUS AREAS:
  - build: [specific commands, conventions]
  - test: [framework, patterns]
  - reviewer: [areas to watch]
  - security: [attack surface]
```

Ask: "Does this look right? Anything to adjust?"

Once confirmed, proceed immediately.

---

## Phase 4: Generate Artifacts

Now generate all project artifacts. **NO MORE QUESTIONS** from here.

### Update PROJECT_SPEC.md

If PROJECT_SPEC.md is still a template (contains `<!-- agentcaddy:template:unfilled -->`),
overwrite it with the real project specification based on your analysis and the
user's input. Remove the marker.

If it was already filled in, update it with any new information from the conversation.

### Update CLAUDE.md

- Replace the generic "Project Overview" with the real project description
- Fill in the "Development Commands" section with actual build/test/lint commands
- Add project-specific conventions (naming, architecture patterns, important files)

### Update AGENTS.md

Create or update AGENTS.md with project-specific conventions and build commands.

### Adapt agent prompts

Edit `prompts/*.txt` — add project context: frameworks used, test patterns,
build commands, architectural conventions, key files to know about.

Edit `.claude/commands/*.md` — add project context: frameworks used, test
patterns, build commands, architectural conventions, key files to know about.

In particular for these agents (build, plan, ralph, pm, reviewer, explorer, test, sre, security, docs, refactor, devops):
- **build**: exact build/test/lint commands for this project
- **test**: test framework, patterns, how to run tests, coverage tools
- **reviewer**: project-specific review focus areas, architecture patterns, common pitfalls
- **security**: project-specific attack surface (APIs, auth, data handling)

### Create ROADMAP.md and RALPH_STATUS.md

Ralph (the autonomous loop coordinator) needs these artifacts to operate.

**ROADMAP.md** — Create from the confirmed project spec:
- Break down features into phases (logical groupings)
- Within each phase, create discrete tasks (one PR-sized unit of work each)
- Each task: ID (e.g. P1-T01), title, description, status (TODO), size (S/M/L/XL)
- Order tasks by dependency — Ralph executes them in order, no skipping
- Include setup tasks first (project structure, CI, core abstractions)
- End each phase with a review/test task

**RALPH_STATUS.md** — Create with initial state:
```markdown
# Ralph Status

## Current State
- Phase: 1
- Last completed: (none)
- Next task: P1-T01
- Iterations this session: 0
- Blockers: none
```


---

## Rules

- Do NOT change the agent structure or permissions — only prompts and instructions
- Do NOT delete anything from the agent templates — only add project-specific context
- Be specific: use actual file paths, actual command names, actual framework names
- Keep prompts concise — agents work better with focused instructions than long essays
