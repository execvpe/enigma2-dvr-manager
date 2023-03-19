.PHONY: typecheck

typecheck: dvr_list.py
	mypy --ignore-missing-imports --disallow-untyped-defs $<
