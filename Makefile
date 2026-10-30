.PHONY: setup run clean sys-deps install uninstall help

PYTHON := python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
APP_MAIN := main.py
APP_NAME := tavessari
APP_ID := pl.septicwolf818.tavessari
LEGACY_APP_NAME := text-editor
LEGACY_APP_ID := pl.septicwolf818.TextEditor
ICON_DIR := $(HOME)/.local/share/icons/hicolor/scalable/apps

setup: $(VENV_PYTHON)

$(VENV_PYTHON): requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PIP) install -r requirements.txt

run: setup
	$(VENV_PYTHON) $(APP_MAIN)

clean:
	rm -rf $(VENV) __pycache__ .pytest_cache
	find . -name "*.pyc" -delete -o -name "__pycache__" -type d -prune -exec rm -rf {} +

# System C libraries / typelibs needed for PyGObject + GTK4 + libadwaita
# (not Python packages, so venv stays isolated with NO --system-site-packages)
sys-deps:
	@if command -v apt-get >/dev/null; then \
		sudo apt-get update && sudo apt-get install -y libgtk-4-1 gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-0 gir1.2-gtksource-5 libgtksourceview-5-0 libcairo2-dev libgirepository-2.0-dev pkg-config python3-dev gobject-introspection; \
	elif command -v dnf >/dev/null; then \
		sudo dnf install -y gtk4 libadwaita gtksourceview5 gobject-introspection cairo-devel gobject-introspection-devel pkg-config python3-devel; \
	elif command -v pacman >/dev/null; then \
		sudo pacman -S --needed gtk4 libadwaita gtksourceview5 gobject-introspection cairo pkgconf base-devel; \
	else \
		echo "Install manually: GTK4, libadwaita, gobject-introspection, cairo, pkg-config"; exit 1; \
	fi

PREFIX ?= $(HOME)/.local/share

install: build
	@echo "== installing to $(PREFIX) ..."
	@rm -rf "$(PREFIX)/$(LEGACY_APP_NAME)"
	@rm -f "$(HOME)/.local/share/applications/$(LEGACY_APP_ID).desktop" "$(ICON_DIR)/$(LEGACY_APP_ID).svg"
	@rm -rf "$(PREFIX)/$(APP_NAME)"
	@mkdir -p "$(PREFIX)/$(APP_NAME)"
	@cp "$(APP_MAIN)" "$(PREFIX)/$(APP_NAME)/"
	@for f in ai_controller.py editor_tab.py file_ops.py find_replace.py ollama.py sidebar.py ui_utils.py; do cp "$$f" "$(PREFIX)/$(APP_NAME)/"; done
	@python3 -m venv "$(PREFIX)/$(APP_NAME)/.venv"
	@"$(PREFIX)/$(APP_NAME)/.venv/bin/python" -m pip install --upgrade pip
	@"$(PREFIX)/$(APP_NAME)/.venv/bin/pip" install -r requirements.txt
	@mkdir -p "$(PREFIX)/$(APP_NAME)/data"
	@cp "data/tavessari.svg" "$(PREFIX)/$(APP_NAME)/data/"
	@mkdir -p $(HOME)/.local/share/applications "$(ICON_DIR)"
	@sed -e 's|@@PREFIX@@|$(PREFIX)|g' -e 's|@@APP_NAME@@|$(APP_NAME)|g' -e 's|@@APP_ID@@|$(APP_ID)|g' Makefile.desktop.tpl > "$(HOME)/.local/share/applications/$(APP_ID).desktop"
	@desktop-file-validate "$(HOME)/.local/share/applications/$(APP_ID).desktop"
	@cp "data/tavessari.svg" "$(ICON_DIR)/$(APP_ID).svg"
	@gtk-update-icon-cache -f "$(HOME)/.local/share/icons/hicolor" >/dev/null 2>&1 || true
	@update-desktop-database "$(HOME)/.local/share/applications" >/dev/null 2>&1 || true
	@echo "== Installed to $(PREFIX)"

uninstall:
	@echo "== uninstalling ..."
	@rm -rf "$(PREFIX)/$(APP_NAME)"
	@rm -rf "$(PREFIX)/$(LEGACY_APP_NAME)"
	@rm -f "$(HOME)/.local/share/applications/$(APP_ID).desktop"
	@rm -f "$(HOME)/.local/share/applications/$(LEGACY_APP_ID).desktop"
	@rm -f "$(ICON_DIR)/$(APP_ID).svg"
	@rm -f "$(ICON_DIR)/$(LEGACY_APP_ID).svg"
	@gtk-update-icon-cache -f "$(HOME)/.local/share/icons/hicolor" >/dev/null 2>&1 || true
	@update-desktop-database "$(HOME)/.local/share/applications" >/dev/null 2>&1 || true
	@echo "== Uninstalled."

build:
	@echo "== build step =="

help:
	@echo "Targets:"
	@echo "  build   - Build step"
	@echo "  install - Install ($(PREFIX)/tavessari default)"
	@echo "  uninstall - Remove installed files"
	@echo ""
	@echo "To install to /opt: sudo make install PREFIX=/opt"
