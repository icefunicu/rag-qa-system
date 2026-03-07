POWERSHELL ?= powershell
PS_FLAGS ?= -NoProfile -ExecutionPolicy Bypass

.PHONY: help up down logs logs-follow export-logs ci test build fmt encoding

help:
	@echo Available targets:
	@echo   make up           - 启动本地环境
	@echo   make down         - 停止本地环境
	@echo   make logs         - 查看最近日志
	@echo   make logs-follow  - 持续跟随日志
	@echo   make export-logs  - 导出日志快照
	@echo   make ci           - 执行回归检查
	@echo   make test         - 运行后端测试
	@echo   make build        - 构建 Docker 镜像
	@echo   make fmt          - 格式化 Go 代码
	@echo   make encoding     - 检查文本文件编码

up:
	$(POWERSHELL) $(PS_FLAGS) -File scripts/dev-up.ps1

down:
	$(POWERSHELL) $(PS_FLAGS) -File scripts/dev-down.ps1 -Force

logs:
	$(POWERSHELL) $(PS_FLAGS) -Command "& .\\logs.bat"

logs-follow:
	$(POWERSHELL) $(PS_FLAGS) -Command "& .\\logs.bat -f"

export-logs:
	$(POWERSHELL) $(PS_FLAGS) -File scripts/aggregate-logs.ps1

ci:
	$(POWERSHELL) $(PS_FLAGS) -File scripts/ci-check.ps1

test:
	cd services/go-api && go test ./...
	cd services/py-rag-service && python -m pytest -q
	cd services/py-worker && python -m pytest -q

build:
	docker compose build --pull

fmt:
	cd services/go-api && go fmt ./...

encoding:
	python scripts/check_encoding.py
