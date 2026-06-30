SHELL         := powershell.exe
.SHELLFLAGS   := -NoProfile -ExecutionPolicy Bypass -Command
PS            := powershell.exe -NoProfile -ExecutionPolicy Bypass -File

.PHONY: help clean deploy upload-assets upload-reference seed-data ui test

help:
	@Write-Host "MusicStream ETL Pipeline - Demo Automation"
	@Write-Host "  make clean             - Destroy all AWS resources"
	@Write-Host "  make deploy            - Full two-phase deploy"
	@Write-Host "  make upload-reference  - Sync reference CSVs + run Glue job"
	@Write-Host "  make seed-data         - Seed sample streams"
	@Write-Host "  make ui                - Launch Streamlit dashboard"
	@Write-Host "  make test              - Run test suite"

clean:
	@Write-Host "==> CLEAN: Destroying all AWS dev resources..."
	$(PS) scripts\clean.ps1

deploy:
	@Write-Host "==> DEPLOY Phase 1: Storage plane + encryption keys..."
	$(PS) scripts\run_with_env.ps1 terraform -chdir=infra/envs/dev init
	$(PS) scripts\run_with_env.ps1 terraform -chdir=infra/envs/dev apply "-target=module.data_lake" "-target=module.kms_data" -auto-approve
	@Write-Host "==> DEPLOY Phase 1.5: Compile + upload code assets..."
	$(PS) scripts\deploy.ps1
	@Write-Host "==> DEPLOY Phase 2: Full infrastructure apply..."
	$(PS) scripts\run_with_env.ps1 terraform -chdir=infra/envs/dev apply -auto-approve
	@Write-Host "==> DEPLOY COMPLETE. Run: make upload-reference && make ui"

upload-assets:
	$(PS) scripts\deploy.ps1

upload-reference:
	$(PS) scripts\upload_reference.ps1

seed-data:
	@Write-Host "==> Seeding sample stream files..."
	$(PS) scripts\run_with_env.ps1 bash scripts/seed_sample_streams.sh dev

ui:
	@Write-Host "==> Launching Streamlit dashboard at http://localhost:8501"
	$(PS) scripts\run_with_env.ps1 streamlit run ui/app.py

test:
	@Write-Host "==> Running unit + integration tests..."
	pytest tests/unit tests/integration -q
