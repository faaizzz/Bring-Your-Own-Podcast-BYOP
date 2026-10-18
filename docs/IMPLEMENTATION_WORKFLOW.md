# Implementation workflow

How a roadmap story goes from the board to `main`. The roadmap is GitHub issues
#1–#36 in `faaizzz/Bring-Your-Own-Podcast-BYOP`, tracked on the project board
(`https://github.com/users/faaizzz/projects/2`).

## 1. Pick the next story

Take the **Todo** item with the lowest `Order` field (it equals the issue
number). Read its "Depends on" section: every dependency issue must already be
closed. If one is not, do that dependency first.

```sh
gh project item-list 2 --owner faaizzz --format json --limit 100
```

## 2. Read the issue

```sh
gh issue view N -R faaizzz/Bring-Your-Own-Podcast-BYOP
```

Read the whole body: Goal, Scope, Acceptance criteria, Technical notes, Out of
scope, Verification. Also read `CLAUDE.md` for conventions.

## 3. Mark it In Progress

Set the project `Status` field to **In Progress** with `gh project item-edit`
(project id from `gh project view 2 --owner faaizzz --format json --jq .id`,
the item id from the item list above, and the Status field/option ids shown in
the project settings).

## 4. Implement

Implement exactly the issue's scope — no more. Satisfy every acceptance
criterion, add tests for new behaviour, and update docs, `.env.example` and
`CLAUDE.md` when conventions or environment variables change.

## 5. Verify

```sh
make check
```

Then run the issue's Verification steps (docker compose is the reference
environment). Fix failures; never weaken or skip tests to get green.

## 6. Commit and push to `main`

Work happens directly on `main` — no branches, no pull requests.

```
<type>(<area>): <summary>

<optional body>

Closes #N
```

```sh
git push origin main
```

## 7. Mark it Done

Set `Status` to **Done**, confirm the issue closed (the `Closes #N` trailer
closes it on push), and continue with the next story.

## If a story cannot be completed

If it needs something unavailable (for example a paid API key), implement what
can be done with mocks and tests, comment on the issue explaining what remains
(`gh issue comment`), leave it open and In Progress, and continue with the next
story whose dependencies are satisfied.
