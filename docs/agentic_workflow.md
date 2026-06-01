# Agentic Workflow — Stick-Holding & Telephone Skill

> This project is built solo, but planned as a relay of specialised agents.
> Every transition between agents must be **complete in writing** — no shared mental state.

---

## 1. The Stick-Holding Principle

At any point in time, **exactly one agent holds the stick**. The agent holding the stick:

1. Has a single, narrow task.
2. Can read any artefact produced by prior agents.
3. Produces *its own* artefact before handing off.
4. Does **not** silently modify a prior agent's artefact — it appends a delta note.

When the stick is dropped (work resumes after a break), the next agent picks up by reading the last completed artefact, **not** by asking "where were we?". If the artefact does not answer that question, the prior agent failed and the artefact must be repaired before continuing.

## 2. The Telephone Skill

In the children's game of *telephone*, information degrades with each hop. The telephone skill is the discipline that prevents that:

| Rule | Reason |
|------|--------|
| **Restate the input on receipt.** First section of every agent's artefact is "What I was given." | Catches misreading early. |
| **Make the output schema explicit.** Last section is "What the next agent will rely on." | Forces the producer to think about the consumer. |
| **Cite the source.** Any claim taken from a prior artefact links to that artefact by filename + heading. Any claim taken from an external doc links via `references.md`. | Prevents drift; future-you can audit. |
| **Externalise assumptions.** If an agent needs to assume something not in the input, it logs the assumption in `decision.md` *before* using it. | Hidden assumptions are the dominant failure mode. |
| **Re-read, do not paraphrase.** When citing a prior decision, copy the exact wording into the new doc, then comment on it. | Paraphrase is the first step of corruption. |

## 3. Relay Roster

| # | Agent role          | Input artefact(s)                          | Output artefact                                      |
|---|---------------------|--------------------------------------------|------------------------------------------------------|
| 1 | Architect           | `Intructions.txt`, sample CSVs             | `master_plan.md`, `decision.md`                      |
| 2 | Repo curator        | (1)                                        | `directory_structure.md`                             |
| 3 | Infra agent         | (1), (2)                                   | `terraform.md`, `security.md`                        |
| 4 | Storage agent       | (1), (3)                                   | `dynamodb_schema.md`                                 |
| 5 | Validation agent    | (1) data section, sample CSVs              | `data_validation.md`                                 |
| 6 | Transform agent     | (1), (5), `dynamodb_schema.md`             | `transformation_logic.md`                            |
| 7 | Glue ops agent      | (5), (6)                                   | `glue_jobs.md`                                       |
| 8 | Ingestion agent     | (5)                                        | `data_handling.md`                                   |
| 9 | Orchestration agent | (5), (6), (8)                              | `step_functions.md`                                  |
| 10 | Reliability agent  | (9), (7)                                   | `error_handling.md`, `file_archival.md`              |
| 11 | Observability agent| (10)                                       | `logging_monitoring.md`                              |
| 12 | QA agent           | (5), (6), (9)                              | `testing_strategy.md`                                |
| 13 | Release agent      | All above                                  | `production_deployment.md`, `sprint_planning.md`     |

## 4. Hand-Off Template

Each `.md` file in `docs/` follows the same shape:

```markdown
# <Stage Name>

## Input
- What I was given (link the prior artefacts).

## Decisions Made Here
- Bullet list (anything material also goes into decision.md).

## Output Schema
- Exactly what the next agent should read first.

## Body
- Detailed plan, snippets, diagrams.

## Hand-off
- Next agent: <name>
- They need: <list>
```

Not every existing doc follows this skeleton verbatim — older docs in this set are pre-formatted — but **new** docs added after this point must.

## 5. When to *Not* Pass the Stick

There are three legitimate reasons to refuse hand-off:

1. **Input is incomplete.** Push back to the prior agent in writing; do not paper over.
2. **A decision required exceeds the agent's scope.** Escalate to `decision.md`.
3. **The relay branches.** If two agents can work in parallel (e.g. validation spec + DynamoDB schema), the stick *forks*. Both forks must converge at a named merge agent (here: orchestration agent).

## 6. When Stuck: Consult `references.md`

If an agent cannot make progress because an AWS service behaviour, a Terraform argument, a PySpark API, or a Python library is unclear, the **first action is to open `references.md`**, not to guess. That file is the curated index of every external source this project depends on, organised by the question the agent is likely asking. After reading, the agent cites the URL in the doc it is editing (or in `decision.md` if the lookup produced a decision). If the answer is genuinely absent from every source linked there, log the gap as a new entry in `references.md` so the next agent does not pay the same cost.

## 7. Anti-Patterns to Avoid

- "I'll figure it out as I code." → The whole point of this relay is that planning makes coding mechanical.
- Cross-referencing memory of a chat instead of a file. → Memory is lossy; files are not.
- Editing a prior doc to retro-fit a current decision. → Append a delta note; do not rewrite history.
- "Quick fix" outside the relay. → Even one-line changes get a `decision.md` line.
