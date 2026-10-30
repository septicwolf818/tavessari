# TAVESSARI

A GTK 4 text editor with tabs, syntax highlighting, a folder browser, find and
replace, and optional AI assistance through a local Ollama server.

## Requirements

- Python 3.10+
- GTK 4 and libadwaita development/runtime libraries
- GtkSourceView 5 is optional; without it, the editor uses a plain GTK text view
- Ollama is optional and only needed for AI actions

Install the system dependencies, create the virtual environment, and launch:

```sh
make sys-deps
make setup
make run
```

To install the desktop application under `~/.local/share`:

```sh
make install
```

Set `OLLAMA_HOST` to use an Ollama server other than `http://localhost:11434`.
