PLUGIN_DIR := plugins/dts2-harness
VERSION := $(shell python3 -c "import json; print(json.load(open('$(PLUGIN_DIR)/.claude-plugin/plugin.json'))['version'])")
DIST := dist

.PHONY: package test check-version

package:
	mkdir -p $(DIST)
	rm -f $(DIST)/dts2-harness-$(VERSION).zip $(DIST)/dts2-marketplace-$(VERSION).zip
	cd $(PLUGIN_DIR) && zip -r -q ../../$(DIST)/dts2-harness-$(VERSION).zip . \
		-x '*/__pycache__/*' '__pycache__/*' '*/.pytest_cache/*' '.pytest_cache/*' \
		'receipts/*' '*/receipts/*' 'review-receipts/*' '*/review-receipts/*'
	git archive --format=zip -o $(DIST)/dts2-marketplace-$(VERSION).zip HEAD

test:
	cd $(PLUGIN_DIR) && python3 -m unittest discover -s tests

check-version:
	python3 $(PLUGIN_DIR)/scripts/bump-version.py $(VERSION) --check
