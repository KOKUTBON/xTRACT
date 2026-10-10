"""xTRACT command-line interface.

Commands:
  xtract serve                     start the web portal and API
  xtract ingest FILE [FILE ...]    ingest files and process them
  xtract process                   run all queued jobs once
  xtract export --format jsonl     export the processed dataset
  xtract engines                   show which OCR engines are available
  xtract benchmark                 run evaluation benchmark suite
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from xtract.config import PlatformConfig
from xtract.core import Platform
from xtract.deployment import DeploymentError, initialize, load_config, preflight
from xtract.intake.service import IntakeError


def cmd_serve(args, config: PlatformConfig) -> int:
    from xtract.api.server import serve

    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.deployment:
        report = preflight(config)
        if report["errors"]:
            print(json.dumps(report, indent=2), file=sys.stderr)
            return 1
    serve(config)
    return 0


def cmd_ingest(args, config: PlatformConfig) -> int:
    platform = Platform(config)
    status = 0
    for name in args.files:
        path = Path(name)
        try:
            if (
                config.allowed_offices is not None
                and (args.office or config.default_office) not in config.allowed_offices
            ):
                raise DeploymentError("Choose an enabled office from the institution deployment.")
            if (
                args.deployment
                and args.institution
                and args.institution != config.default_institution
            ):
                raise DeploymentError("This deployment belongs to another institution.")
            doc, _ = platform.intake.ingest_document(
                institution_id=args.institution or config.default_institution,
                office_id=args.office or config.default_office,
                document_family=args.family,
                filename=path.name,
                content=path.read_bytes(),
                actor_id="cli",
            )
            print(f"ingested  {path.name} -> {doc['document_id']}")
        except (OSError, IntakeError, DeploymentError) as exc:
            print(f"skipped   {path.name}: {getattr(exc, 'message', exc)}", file=sys.stderr)
            status = 1
    if not args.no_process:
        platform.process_pending()
        for hit in platform.projections.search_documents(limit=len(args.files))["hits"]:
            print(
                f"{hit['workflow_stage']:<20} {hit['document_type_display_name']:<30} {hit['source_filename']}"
            )
    return status


def cmd_process(args, config: PlatformConfig) -> int:
    passes = Platform(config).process_pending()
    print(f"processed {passes} worker pass(es)")
    return 0


def cmd_export(args, config: PlatformConfig) -> int:
    exporter = Platform(config).exporter
    institution = config.default_institution if args.deployment else None
    if args.format == "jsonl":
        content = "".join(exporter.iter_jsonl(args.stage, args.include_text, institution))
    elif args.format == "json":
        content = json.dumps(
            exporter.export_json(args.stage, institution), indent=2, ensure_ascii=False
        )
    else:
        content = exporter.export_csv(args.stage, institution)
    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(content)
    return 0


def cmd_engines(args, config: PlatformConfig) -> int:
    from xtract.ocr.engines import default_engines

    for engine_id, engine in default_engines(languages=config.tesseract_lang).items():
        available, reason = engine.availability()
        state = "available" if available else "unavailable"
        print(f"{engine_id:<10} {state:<12} {reason}")
    return 0


def cmd_benchmark(args, config: PlatformConfig) -> int:
    from benchmarks.run_benchmark import run_benchmarks

    return run_benchmarks(quiet=args.quiet)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xtract", description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", help="directory for the database and stored files")
    parser.add_argument(
        "--deployment", help="institution bundle directory containing deployment.json"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser(
        "init-institution", help="create a separate institution configuration bundle"
    )
    setup.add_argument("--output", required=True)
    setup.add_argument("--institution", required=True)
    setup.add_argument("--name", required=True)
    setup.add_argument("--pack", choices=["general", "it-pa"], default="general")
    setup.add_argument("--locale", default="en")

    sub.add_parser("validate-config", help="validate institution bundle contracts and references")
    sub.add_parser("doctor", help="check effective credentials, assets and OCR availability")
    issue = sub.add_parser(
        "issue-token", help="provision a user token through trusted server administration"
    )
    issue.add_argument("--user", required=True)
    issue.add_argument(
        "--role",
        choices=["admin", "supervisor", "operator", "viewer", "auditor"],
        default="operator",
    )
    issue.add_argument("--office")
    issue.add_argument("--expires-in", type=int, default=3600)

    serve = sub.add_parser("serve", help="start the web portal and API")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.set_defaults(func=cmd_serve)

    ingest = sub.add_parser("ingest", help="ingest one or more files")
    ingest.add_argument("files", nargs="+")
    ingest.add_argument("--family", default="auto", help="document family code (default: auto)")
    ingest.add_argument("--institution")
    ingest.add_argument("--office")
    ingest.add_argument("--no-process", action="store_true", help="only queue the files")
    ingest.set_defaults(func=cmd_ingest)

    process = sub.add_parser("process", help="run queued jobs until none are ready")
    process.set_defaults(func=cmd_process)

    export = sub.add_parser("export", help="export processed documents")
    export.add_argument("--format", choices=["jsonl", "json", "csv"], default="jsonl")
    export.add_argument("--stage", default="validated", help="validated, all, or a workflow stage")
    export.add_argument("--include-text", action="store_true", help="include OCR text (jsonl)")
    export.add_argument("--output", "-o")
    export.set_defaults(func=cmd_export)

    engines = sub.add_parser("engines", help="show OCR engine availability")
    engines.set_defaults(func=cmd_engines)

    bench = sub.add_parser("benchmark", help="run reproducible benchmark suite")
    bench.add_argument("-q", "--quiet", action="store_true", help="only show final summary table")
    bench.set_defaults(func=cmd_benchmark)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.command == "init-institution":
            result = initialize(
                Path(args.output), args.institution, args.name, args.pack, args.locale
            )
            print(f"Created institution bundle: {result}")
            return 0
        if args.command in ("validate-config", "doctor", "issue-token") and not args.deployment:
            raise DeploymentError("Use --deployment to select an institution bundle.")
        config = load_config(Path(args.deployment)) if args.deployment else PlatformConfig()
        if args.data_dir:
            config.data_dir = Path(args.data_dir).resolve()
            config.database_path = str(config.data_dir / "xtract.db")
            config.storage_root = config.data_dir / "storage"
        if args.command == "validate-config":
            print(f"Valid institution configuration: {config.default_institution}")
            return 0
        if args.command == "doctor":
            report = preflight(config)
            print(json.dumps(report, indent=2))
            return int(bool(report["errors"]))
        if args.command == "issue-token":
            from xtract.auth.service import AuthService

            if not (config.jwt_secret or config.api_token):
                raise DeploymentError("Configure a signing secret before provisioning users.")
            if not 1 <= args.expires_in <= 86400:
                raise DeploymentError("Token lifetime must be between 1 and 86400 seconds.")
            office = args.office or config.default_office
            if office not in config.allowed_offices:
                raise DeploymentError("Choose an enabled institution office.")
            print(
                AuthService(config).create_token(
                    args.user, roles=[args.role], office_id=office, expires_in=args.expires_in
                )
            )
            return 0
        return args.func(args, config)
    except DeploymentError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
