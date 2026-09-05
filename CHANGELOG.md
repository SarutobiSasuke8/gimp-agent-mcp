# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-05

First release.

### Added

- GIMP 3 bridge plug-in: loopback TCP, token-checked, GLib main-thread dispatch, persistent Python namespace.
- MCP server with 21 tools: session (`status`, `launch`, `shutdown`), images (`list`, `info`, `new`, `open`, `export`, `close`, `render`), PDB (`search`, `describe`, `call`), GEGL filters (`search`, `describe`, `apply`, `layer_effects`), `run_python`, recipes (`list`, `run`, `batch`).
- Runtime introspection of PDB arguments and GEGL properties, with JSON coercion for images, items, item arrays, colours, files, enums and scalars.
- Recipes: `telegram_sticker`, `fit_and_export`.
- CLI: `serve`, `install-plugin`, `doctor`, `launch`, `smoke`.
- Live smoke test covering every tool family against a headless GIMP, plus GIMP-free unit tests and CI on Ubuntu and Windows.
