# Course checkpoints. Each target takes the step number: make check STEP=07
PY ?= python

.PHONY: check capture capture-check

check:
	@if [ -z "$(STEP)" ]; then echo "usage: make check STEP=NN"; exit 2; fi
	@$(PY) course/tools/check.py $(STEP)

capture:
	@if [ -z "$(STEP)" ]; then echo "usage: make capture STEP=NN"; exit 2; fi
	@$(PY) course/tools/capture.py $(STEP)

capture-check:
	@if [ -z "$(STEP)" ]; then echo "usage: make capture-check STEP=NN"; exit 2; fi
	@$(PY) course/tools/capture.py $(STEP) --check
