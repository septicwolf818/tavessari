.PHONY: setup run clean sys-deps

PYTHON := python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
APP_MAIN := main.py

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
