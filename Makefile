SHELL         := powershell.exe
.SHELLFLAGS   := -NoProfile -ExecutionPolicy Bypass -Command
PS            := powershell.exe -NoProfile -ExecutionPolicy Bypass -File

.PHONY: help clean deploy upload-assets upload seed-data ui test

help:
	$(PS) scripts\help.ps1

clean:
	$(PS) scripts\clean.ps1

deploy:
	$(PS) scripts\run_with_env.ps1 terraform -chdir=infra/envs/dev init
	$(PS) scripts\run_with_env.ps1 terraform -chdir=infra/envs/dev apply "-target=module.data_lake" "-target=module.kms_data" -auto-approve
	$(PS) scripts\deploy.ps1
	$(PS) scripts\run_with_env.ps1 terraform -chdir=infra/envs/dev apply -auto-approve
	$(PS) scripts\upload_reference.ps1

upload-assets:
	$(PS) scripts\deploy.ps1

upload:
	$(PS) scripts\upload_reference.ps1

seed-data:
	$(PS) scripts\run_with_env.ps1 bash scripts/seed_sample_streams.sh dev

ui:
	$(PS) scripts\run_with_env.ps1 streamlit run ui/app.py

test:
	pytest tests/unit tests/integration -q
