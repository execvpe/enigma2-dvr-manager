.PHONY: check-typing

check-typing: dvr_list.py
	mypy --ignore-missing-imports --disallow-untyped-defs $<
