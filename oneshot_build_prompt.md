# Master One-Shot Build Instructions

Copy and paste this entire prompt into your AI coding assistant to start the build process.

---

```markdown
You are an expert Cloud Data Engineer and Premium Full-stack Developer. You are paired with a human operator to build the entire Streaming Analytics ETL Pipeline and Streamlit UI Dashboard.

### ── SOURCE OF TRUTH ──────────────────────────────────────────────────
1. The file `Intructions.txt` at the root of the workspace is the GOLD STANDARD. Its requirements must NEVER be violated.
2. The architectural decisions, design layouts, and technical constraints documented in `CLAUDE.md` and all files under the `docs/` folder are binding. Refer to `docs/master_plan.md` first.
3. The operator guide `human.md` contains the commands to run, verify, and tear down the system.

### ── YOUR GOAL ───────────────────────────────────────────────────────
Implement all code, IaC configs, scripts, and tests required by the system, ensuring every sprint exit gate in `docs/sprint_planning.md` is met and verified.

### ── REQUIRED SKILLS & TECHNICAL GUIDELINES ─────────────────────────

#### 1. Terraform & Infrastructure (IaC)
- Write modular, clean, and highly secure Terraform configurations in `infra/` following `docs/terraform.md`.
- **Least Privilege:** Do not use wildcards (`*`) in IAM role policies. Every action must be explicit.
- **KMS Policies:** Use root-principal delegation to avoid circular dependencies with roles.

#### 2. Python Backend & Data Pipelines
- **T1 Schema Gate:** Implement the Python 3.12 Lambda in `lambda/validate_schema/` using a 4 KB range request to check headers before triggering Glue.
- **PySpark Transformation:** Implement the Glue PySpark 4.0 job in `glue/pyspark/transform_kpis.py` following `docs/transformation_logic.md` to compute the six genre-level daily KPIs.
- **DynamoDB Loader:** Implement the Glue Python Shell job in `glue/python_shell/load_dynamodb.py` to batch-write KPIs to DynamoDB.
- **Adaptive Retry & Shared Utils:** Implement the shared library in `glue/shared/` containing the DynamoDB client wrapper with adaptive retry (D-26). Every component must use this wrapper.
- **JSON Logging & PII:** Log only in JSON using the structured log format. **Never log PII fields** like `user_name` or `user_country`.

#### 3. Premium Streamlit UI Dashboard (Frontend & UI Skills)
- Implement the Streamlit dashboard in `ui/app.py` and `ui/pages/` according to `docs/ui.md`.
- **Aesthetic Excellence:** Create a highly polished, premium user interface. Use custom CSS styling, curated color palettes, elegant dark mode themes, clean Google Fonts typography, and subtle hover/transition micro-animations. Avoid generic styling.
- **Interactive Visualizations:** Build beautiful, interactive charts using Plotly/Pandas for trends and top-ranking metrics.
- **Direct Access & Mock Mode:** Connect directly to DynamoDB tables via the shared `boto3` helper (no API Gateway). Ensure a toggle for `MOCK_MODE=true` is supported using the fixture data.
- **No PII:** Never render raw user names, emails, or countries in the UI. Display aggregated metrics only.

### ── WORKFLOW & COMMIT GUIDELINES ───────────────────────────────────

- **Sticking to the Plan:** Build components systematically, focusing on one sprint at a time as outlined in `docs/sprint_planning.md`.
- **NO BIG BANG COMMITS:** You must commit your changes incrementally. Stage and commit files on a **per-file basis** using:
  `git add <file-path>`
  `git commit -m "<type>(<scope>): <description>"`
  
  Use the standard commit types:
  - `feat`: New features (e.g. `feat(glue): add pyspark transformation job`)
  - `fix`: Bug fixes (e.g. `fix(infra): correct Lambda IAM execution role policy`)
  - `docs`: Documentation updates (e.g. `docs(readme): clarify UI run commands`)
  - `refactor`: Structural code cleanup
  - `test`: Unit/integration tests addition/updates

- **Security scanning:** Ensure that no secrets or `.env` files are tracked or committed.

### ── EXECUTION & TESTING ──────────────────────────────────────────
Before completing any sprint, you must verify the work by running tests and quality checks as documented in `human.md` Section 10:
1. Unit & integration tests: `pytest tests/unit tests/integration -q`
2. Terraform validation and linting: `terraform validate`, `tflint`, and `checkov -d infra/`
3. SAST scanning: `semgrep --config p/python glue/ lambda/ ui/`

Begin by reviewing the files in the workspace (starting with `CLAUDE.md` and `docs/master_plan.md`), formulate your implementation strategy, and start executing the sprints one by one.
```
