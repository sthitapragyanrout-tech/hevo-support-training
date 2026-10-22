import io
import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook

from apps.accounts.models import Role
from apps.catalog import importer, services
from apps.catalog.models import Activity, ContentNode, Course

pytestmark = pytest.mark.django_db

CSV = """Module,Lesson,Section,Description,Minutes,Activity,Activity Type,URL
Foundations,Hevo Architecture,What is Hevo?,An intro,10,Intro reading,Reading,https://docs.example/intro
,,Pipelines,,15,Pipeline quiz,Quiz,
,Sources,,Where data starts,,,,
Connectors,MySQL,Setup,,20,,,
"""


def csv_file(text=CSV, name="plan.csv"):
    return SimpleUploadedFile(name, text.encode(), content_type="text/csv")


def xlsx_file(rows, name="plan.xlsx"):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


def plan_for(text):
    headers, rows = importer.read_table("x.csv", text.encode())
    return importer.build_plan(headers, rows, importer.suggest_mapping(headers))


class TestReading:
    def test_header_synonyms_including_legacy_names(self):
        mapping = importer.suggest_mapping(
            ["Segment", "Topic", "Subtopic", "Duration", "Type", "Link"]
        )
        assert mapping["module"] == "Segment"
        assert mapping["lesson"] == "Topic"
        assert mapping["section"] == "Subtopic"
        assert mapping["minutes"] == "Duration"
        assert mapping["activity_type"] == "Type"
        assert mapping["url"] == "Link"
        assert mapping["activity"] is None

    def test_semicolon_csv_and_latin1_are_understood(self):
        text = "Module;Lesson\nÉtude;Intro\n"
        headers, rows = importer.read_table("x.csv", text.encode("latin-1"))
        assert headers == ["Module", "Lesson"] and rows == [["Étude", "Intro"]]

    def test_rejects_unsupported_oversized_and_corrupt_files(self):
        with pytest.raises(importer.ImportFileError):
            importer.read_table("x.pdf", b"%PDF")
        with pytest.raises(importer.ImportFileError):
            importer.read_table("x.csv", b"a" * (importer.MAX_BYTES + 1))
        with pytest.raises(importer.ImportFileError):
            importer.read_table("x.xlsx", b"not a zip")
        with pytest.raises(importer.ImportFileError):
            importer.read_table("x.csv", b"\n\n")

    def test_row_limit(self):
        text = "Module\n" + "\n".join(f"M{i}" for i in range(importer.MAX_ROWS + 1))
        with pytest.raises(importer.ImportFileError):
            importer.read_table("x.csv", text.encode())

    def test_xlsx_cells_are_read_as_text(self):
        data = xlsx_file([["Module", "Lesson", "Minutes"], ["M", "L", 15]]).read()
        headers, rows = importer.read_table("x.xlsx", data)
        assert rows == [["M", "L", "15"]]


class TestPlan:
    def test_fill_down_builds_the_hierarchy(self):
        plan = plan_for(CSV)
        assert plan.errors == []
        assert plan.counts == {"modules": 2, "lessons": 3, "sections": 3, "activities": 2}
        foundations = plan.modules[0]
        assert [c.title for c in foundations.children] == ["Hevo Architecture", "Sources"]
        architecture = foundations.children[0]
        # "Pipelines" inherited Module + Lesson from the rows above it.
        assert [s.title for s in architecture.children] == ["What is Hevo?", "Pipelines"]
        assert architecture.children[1].minutes == 15
        assert architecture.children[0].activities[0].url == "https://docs.example/intro"
        assert foundations.children[1].description == "Where data starts"

    def test_activity_type_aliases(self):
        plan = plan_for(
            "Module,Lesson,Activity,Type\n"
            "M,L,A,Quiz\n,,B,Chat simulation\n,,C,video\n,,D,Simulation\n"
        )
        types = [a.activity_type for a in plan.modules[0].children[0].activities]
        assert types == ["mcq", "bot_sim", "video", "manual_sim"]

    @pytest.mark.parametrize(
        "text,fragment,row",
        [
            ("Module,Lesson\n,Orphan lesson\n", "no module", 2),
            ("Module,Lesson,Section\nM,,Orphan section\n", "no lesson", 2),
            ("Module,Lesson,Activity,Type\nM,L,A,hologram\n", "Unknown activity type", 2),
            ("Module,Lesson,Activity,Type\nM,L,A,\n", "needs a type", 2),
            ("Module,Lesson,Activity,Type\nM,,A,Reading\n", "no lesson or section", 2),
            ("Module,Lesson,Minutes\nM,L,soon\n", "number of minutes", 2),
        ],
    )
    def test_row_numbered_errors(self, text, fragment, row):
        plan = plan_for(text)
        assert plan.errors, text
        assert plan.errors[0].row == row
        assert fragment.lower() in plan.errors[0].message.lower()

    def test_duplicate_titles_warn_but_do_not_block(self):
        plan = plan_for("Module,Lesson\nM,Same\nM2,Other\n,Same\n")
        assert plan.errors == []
        assert plan.warnings == []  # different parents: fine
        plan = plan_for("Module,Lesson\nM,Same\n,Same\n")
        assert [w.row for w in plan.warnings] == [3]
        assert plan.errors == []

    def test_unmapped_structure_is_an_error(self):
        headers, rows = importer.read_table("x.csv", b"Foo,Bar\n1,2\n")
        plan = importer.build_plan(headers, rows, importer.suggest_mapping(headers))
        assert plan.errors and plan.errors[0].row is None

    def test_blank_rows_are_ignored(self):
        plan = plan_for("Module,Lesson\nM,L\n,\n,\n")
        assert plan.errors == [] and plan.counts["lessons"] == 1


@pytest.fixture
def trainer_client(client, make_role_user):
    client.force_login(make_role_user(Role.Name.TRAINER))
    return client


@pytest.fixture
def course(trainer_client):
    response = trainer_client.post(
        reverse("authoring_api:courses"),
        data=json.dumps({"title": "Imported course"}),
        content_type="application/json",
    )
    return response.json()


def upload(client, name, course_id, file, **extra):
    return client.post(reverse(f"authoring_api:{name}", args=[course_id]), {"file": file, **extra})


class TestPreviewEndpoint:
    def test_preview_reports_counts_outline_and_writes_nothing(self, trainer_client, course):
        response = upload(trainer_client, "import-preview", course["id"], csv_file())
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["counts"] == {"modules": 2, "lessons": 3, "sections": 3, "activities": 2}
        assert body["outline"][0]["title"] == "Foundations"
        assert body["mapping"]["module"] == "Module"
        assert (
            ContentNode.objects.filter(course_version__course_id=course["id"]).count() == 1
        )  # root only

    def test_preview_surfaces_errors_with_row_numbers(self, trainer_client, course):
        bad = csv_file("Module,Lesson,Activity,Type\nM,L,A,hologram\n")
        body = upload(trainer_client, "import-preview", course["id"], bad).json()
        assert body["ok"] is False
        assert body["errors"][0]["row"] == 2

    def test_manual_mapping_overrides_suggestions(self, trainer_client, course):
        file = csv_file("Week,Topic name\nW1,Intro\n")
        mapping = json.dumps({"module": "Week", "lesson": "Topic name"})
        body = upload(trainer_client, "import-preview", course["id"], file, mapping=mapping).json()
        assert body["ok"] is True and body["counts"]["lessons"] == 1

    def test_unreadable_file_is_a_400(self, trainer_client, course):
        response = upload(trainer_client, "import-preview", course["id"], csv_file(name="plan.pdf"))
        assert response.status_code == 400
        assert ".csv" in response.json()["detail"]

    def test_learners_cannot_import(self, client, make_role_user, course):
        client.force_login(make_role_user(Role.Name.LEARNER))
        assert upload(client, "import-preview", course["id"], csv_file()).status_code == 403


class TestCommitEndpoint:
    def test_csv_import_creates_the_tree_through_the_services(self, trainer_client, course):
        response = upload(trainer_client, "import-commit", course["id"], csv_file())
        assert response.status_code == 201
        assert response.json()["counts"] == {
            "modules": 2,
            "lessons": 3,
            "sections": 3,
            "activities": 2,
        }

        version = services.open_version(Course.objects.get(pk=course["id"]))
        kinds = list(
            version.nodes.exclude(kind="course").order_by("id").values_list("kind", flat=True)
        )
        assert (
            kinds.count("segment") == 2
            and kinds.count("topic") == 3
            and kinds.count("subtopic") == 3
        )

        reading = Activity.objects.get(title="Intro reading")
        assert reading.activity_type == "reading"
        assert reading.config["source_url"] == "https://docs.example/intro"
        quiz = Activity.objects.get(title="Pipeline quiz")
        assert quiz.activity_type == "mcq"

        # Imported activities that still need content show up as such.
        detail = trainer_client.get(reverse("authoring_api:course", args=[course["id"]])).json()
        by_title = {a["title"]: a for n in _walk(detail["tree"]["root"]) for a in n["activities"]}
        assert by_title["Intro reading"]["needs_setup"] is False
        assert by_title["Pipeline quiz"]["needs_setup"] is True

    def test_xlsx_import(self, trainer_client, course):
        file = xlsx_file(
            [
                ["Module", "Lesson", "Section", "Minutes"],
                ["M1", "L1", "S1", 12],
                [None, None, "S2", 8],
            ]
        )
        response = upload(trainer_client, "import-commit", course["id"], file)
        assert response.status_code == 201
        assert response.json()["counts"] == {
            "modules": 1,
            "lessons": 1,
            "sections": 2,
            "activities": 0,
        }
        assert ContentNode.objects.get(title="S2").estimated_minutes == 8

    def test_errors_block_the_import_and_nothing_is_written(self, trainer_client, course):
        bad = csv_file("Module,Lesson,Activity,Type\nGood,L,A,Reading\nBad,L2,B,hologram\n")
        response = upload(trainer_client, "import-commit", course["id"], bad)
        assert response.status_code == 400
        assert ContentNode.objects.filter(course_version__course_id=course["id"]).count() == 1

    def test_import_appends_to_existing_content(self, trainer_client, course):
        upload(trainer_client, "import-commit", course["id"], csv_file("Module,Lesson\nA,A1\n"))
        upload(trainer_client, "import-commit", course["id"], csv_file("Module,Lesson\nB,B1\n"))
        titles = list(
            ContentNode.objects.filter(kind="segment", course_version__course_id=course["id"])
            .order_by("order")
            .values_list("title", flat=True)
        )
        assert titles == ["A", "B"]

    def test_cannot_import_into_a_locked_course(
        self, trainer_client, client, make_role_user, course
    ):
        upload(
            trainer_client,
            "import-commit",
            course["id"],
            csv_file("Module,Lesson,Description\nM,L,Hook\n"),
        )
        trainer_client.post(reverse("authoring_api:submit", args=[course["id"]]))
        response = upload(trainer_client, "import-commit", course["id"], csv_file())
        assert response.status_code == 409


def _walk(node):
    yield node
    for child in node["children"]:
        yield from _walk(child)
