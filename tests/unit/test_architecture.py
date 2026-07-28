from pathlib import Path

PACKAGE_MARKERS = (
    "app/__init__.py",
    "app/modules/__init__.py",
    "app/modules/financial/__init__.py",
    "app/modules/financial/domain/__init__.py",
    "app/modules/financial/infra/__init__.py",
    "app/modules/financial/service/__init__.py",
    "app/modules/health/__init__.py",
    "app/modules/health/interface/__init__.py",
    "app/modules/knowledge/__init__.py",
    "app/modules/knowledge/domain/__init__.py",
    "app/modules/knowledge/infra/__init__.py",
    "app/modules/knowledge/interface/__init__.py",
    "app/modules/knowledge/service/__init__.py",
)

LEGACY_SOURCE_FILES = (
    "app/api/health.py",
    "app/api/query.py",
    "app/application/collect_company_financials.py",
    "app/application/financial_files.py",
    "app/application/render_financial_markdown.py",
    "app/domain/financial.py",
    "app/embeddings.py",
    "app/infrastructure/opendart.py",
    "app/ingestion/chunker.py",
    "app/ingestion/markdown.py",
    "app/ingestion/service.py",
    "app/models.py",
    "app/retrieval.py",
)


def test_application_packages_have_markers() -> None:
    assert [path for path in PACKAGE_MARKERS if not Path(path).is_file()] == []


def test_domain_modules_do_not_depend_on_outer_layers() -> None:
    forbidden = ("fastapi", "sqlalchemy", "httpx", ".infra", ".interface")
    domain_files = Path("app/modules").glob("*/domain/*.py")

    violations = {
        str(path): marker
        for path in domain_files
        for marker in forbidden
        if marker in path.read_text()
    }

    assert violations == {}


def test_legacy_backend_sources_are_removed() -> None:
    assert [path for path in LEGACY_SOURCE_FILES if Path(path).exists()] == []
