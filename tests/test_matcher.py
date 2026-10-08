from app.matcher import suggest
from app.toolkit import Entry


def cat(**skills):
    return {n: Entry("skill", n, d, "") for n, d in skills.items()}


def test_suggests_by_overlap_and_area():
    catalog = cat(**{"frontend-data-tables": "Server-side table with pagination and filters",
                     "frontend-theming": "Dark mode and color tokens",
                     "backend-fastapi": "FastAPI router conventions",
                     "backend-api-design": "REST API error format"})
    got = suggest("Panel web con tabla paginada y API REST", catalog)
    assert "frontend-data-tables" in got and "backend-api-design" in got
    assert "frontend-theming" not in got


def test_nothing_matches():
    assert suggest("zzz", cat(a="foo bar")) == []


def test_agents_never_suggested():
    catalog = {"p": Entry("agent", "p", "api planner", "")}
    assert suggest("api", catalog) == []
