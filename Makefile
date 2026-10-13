.PHONY: setup dev test build run
PORT ?= 8010
setup:
	python3 -m venv .venv && .venv/bin/pip install -e '.[dev,voice]'
	cd composer && npm install
	cd frontend && npm install
dev:
	.venv/bin/uvicorn studio.app:app --host 127.0.0.1 --port $(PORT) --reload & UV=$$!; trap 'kill $$UV' EXIT INT TERM; cd frontend && npm run dev
build:
	cd frontend && npm run build
run: build
	.venv/bin/uvicorn studio.app:app --host 127.0.0.1 --port $(PORT)
test:
	.venv/bin/pytest -v
