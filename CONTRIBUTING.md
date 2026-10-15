# Contributing to xTRACT

Contributions are welcome: bug reports, extraction rules for new document types, OCR engine adapters, protocol connectors, translations of the portal, and documentation.

## Getting Started

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
make ci
```

`make ci` runs Ruff (linting and formatting checks) and the full test suite. Tests that require Tesseract are skipped automatically when the binary is not present.

Run the application locally with `make run` (or `xtract serve`) and open <http://127.0.0.1:8000>.

## Guidelines

- Open an issue first for architectural changes or additions to the JSON Schemas in [`src/xtract/contracts/schemas/`](src/xtract/contracts/schemas/).
- Keep schemas, configuration in `config/`, and contracts in sync — `tests/test_contracts.py` automatically validates all configuration against the schemas.
- Use synthetic content in tests, benchmarks, and examples. Never commit real documents, personal data, credentials, or runtime `data/` directories.
- Keep operator-facing text clear, concise, and accessible.
- Include unit tests and run `make ci` before submitting pull requests.

## Adding a Document Type

1. Add the fields and validation patterns to `config/field-taxonomy.v1.json`.
2. Add label aliases and value extraction regexes to `config/alias-dictionary.v1.json`.
3. Add detection keywords to `config/extraction-policy.v1.json`.
4. Add synthetic test documents to `benchmarks/dataset/` and update `ground_truth.json`.
5. Run `make ci` and `xtract benchmark` to verify classification and extraction accuracy.

See [docs/configuration.md](docs/configuration.md) for detailed reference.

## License

By contributing, you agree that your contributions are licensed under the [Apache-2.0 License](LICENSE).

## Community participation

Follow the [communication guidelines](COMMUNICATION.md) and [organizational governance](GOVERNANCE.md). Keep security and conduct reports confidential and use a verified private channel; never include sensitive details in a public issue. Maintainers verify the reporting contacts and channels listed in the [readiness checklist](RELEASE_CHECKLIST.md).

## KOKUTBON contribution principles

Contribute under the existing **Apache-2.0** license in [LICENSE](LICENSE). You retain copyright in your work. Submit only work you are entitled to share, identify third-party sources and preserve their notices. No copyright assignment or paid membership is required.

Open an issue for substantial proposals, then submit a focused pull request from a branch or fork. Describe the problem, implementation, relevant checks and any privacy, accessibility, migration or safety impact. Use synthetic fixtures and sanitized logs. Maintainer review and passing relevant CI checks are expected before merging. A sole maintainer may merge their own change after checks pass and must record the rationale; no fictitious second reviewer is required.

Small documentation, translation, accessibility and reproducibility improvements are welcome. Funding does not determine review priority. Follow [communication guidelines](COMMUNICATION.md) and [the sponsorship policy](SPONSORSHIP.md).
