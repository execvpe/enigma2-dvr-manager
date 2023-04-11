.PHONY: typecheck

typecheck: dvr_manager.py
	mypy --ignore-missing-imports --disallow-untyped-defs $<
