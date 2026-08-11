"""The description rules are the product's judgement. Pin them down."""

import pytest

from app.models.port_info import ProcessInfo
from app.services.description_resolver import UNKNOWN, DescriptionResolver


def proc(name="", cmdline=None, exe=None, pid=4321, username=None, accessible=True):
    return ProcessInfo(
        pid=pid,
        name=name,
        exe=exe,
        cmdline=cmdline,
        username=username,
        create_time=1000.0,
        exists=True,
        accessible=accessible,
    )


@pytest.fixture
def resolver():
    return DescriptionResolver()


# --------------------------------------------------------------- command line


@pytest.mark.parametrize(
    "cmdline, expected",
    [
        (r"C:\Python311\python.exe -m uvicorn main:app --port 8000", "FastAPI / Uvicorn"),
        (r"python.exe -m gunicorn wsgi:app -b 127.0.0.1:8000", "Gunicorn (WSGI)"),
        (r"python C:\work\shop\manage.py runserver 0.0.0.0:8000", "Django"),
        (r"python -m django runserver", "Django"),
        (r"python -m flask run", "Flask"),
        (r"python -m streamlit run app.py", "Streamlit"),
        (r"python -m http.server 8000", "Python HTTP server"),
        (r"python -m celery -A proj worker", "Celery worker"),
        (r"python C:\agents\weather_mcp_server.py", "MCP server"),
    ],
)
def test_python_command_lines(resolver, cmdline, expected):
    assert resolver.resolve(8000, proc("python.exe", cmdline=cmdline)) == expected


@pytest.mark.parametrize(
    "cmdline, expected",
    [
        (r"node C:\app\node_modules\next\dist\bin\next dev", "Next.js"),
        (r"node C:\app\node_modules\.bin\vite --host", "Vite dev server"),
        (r"node C:\app\node_modules\nuxt\bin\nuxt.mjs dev", "Nuxt"),
        (r"node C:\app\node_modules\.bin\react-scripts start", "Create React App"),
        (r"node C:\app\node_modules\.bin\nodemon server.js", "Node.js (nodemon)"),
        (r"node C:\app\node_modules\.bin\astro dev", "Astro"),
        (r"node C:\app\node_modules\.bin\storybook dev -p 6006", "Storybook"),
    ],
)
def test_node_command_lines(resolver, cmdline, expected):
    assert resolver.resolve(3000, proc("node.exe", cmdline=cmdline)) == expected


def test_command_line_beats_process_name(resolver):
    # node.exe alone would only give "Node.js process".
    info = proc("node.exe", cmdline=r"node C:\x\node_modules\.bin\vite")
    assert resolver.resolve(5173, info) == "Vite dev server"


def test_directory_name_alone_does_not_trigger_a_match(resolver):
    """``vite-app`` is a folder name, not evidence that Vite is running."""
    info = proc("node.exe", cmdline=r"node C:\code\vite-app\server\index.js")
    assert resolver.resolve(3000, info) == "Node.js process"


def test_a_next_project_inside_a_vite_named_folder_resolves_to_next(resolver):
    info = proc(
        "node.exe",
        cmdline=r"node C:\code\vite-app\node_modules\next\dist\bin\next dev",
    )
    assert resolver.resolve(3000, info) == "Next.js"


# ------------------------------------------------------------ executable name


@pytest.mark.parametrize(
    "name, expected",
    [
        ("postgres.exe", "PostgreSQL"),
        ("redis-server.exe", "Redis"),
        ("mongod.exe", "MongoDB"),
        ("mysqld.exe", "MySQL"),
        ("nginx.exe", "nginx"),
        ("ollama.exe", "Ollama"),
        ("dockerd.exe", "Docker daemon"),
        ("code.exe", "Visual Studio Code"),
    ],
)
def test_process_names(resolver, name, expected):
    assert resolver.resolve(9999, proc(name)) == expected


def test_name_is_matched_from_the_executable_path_when_name_is_missing(resolver):
    info = proc("", exe=r"C:\Program Files\PostgreSQL\16\bin\postgres.exe")
    assert resolver.resolve(5432, info) == "PostgreSQL"


# ----------------------------------------------------------------- port hints


def test_port_hint_is_used_when_the_process_says_nothing(resolver):
    assert resolver.resolve(3389, proc("", pid=0)) == "Remote Desktop"


def test_port_hint_wins_for_shared_windows_host_processes(resolver):
    info = proc("svchost.exe", username="NT AUTHORITY\\SYSTEM")
    assert resolver.resolve(135, info) == "Windows RPC endpoint mapper"
    assert resolver.resolve(49670, info) == "Windows service host"


def test_port_alone_never_overrides_a_known_runtime(resolver):
    """Port 5432 does not make a bare python.exe into PostgreSQL."""
    assert resolver.resolve(5432, proc("python.exe")) == "Python process"


# ------------------------------------------------------------------ fallbacks


@pytest.mark.parametrize(
    "name, expected",
    [
        ("python.exe", "Python process"),
        ("pythonw.exe", "Python process"),
        ("node.exe", "Node.js process"),
        ("java.exe", "Java application"),
        ("dotnet.exe", ".NET application"),
    ],
)
def test_generic_families(resolver, name, expected):
    assert resolver.resolve(45678, proc(name)) == expected


def test_unknown_stays_unknown(resolver):
    assert resolver.resolve(45678, proc("mystery.exe")) == UNKNOWN


def test_inaccessible_process_is_reported_honestly(resolver):
    info = ProcessInfo(pid=900, name="", exists=True, accessible=False)
    assert resolver.resolve(45678, info) == "Access restricted"


# ------------------------------------------------------------------- overrides


def test_custom_description_overrides_inference():
    resolver = DescriptionResolver({"8000": "AI Backend"})
    info = proc("python.exe", cmdline="python -m uvicorn main:app")
    assert resolver.resolve_automatic(8000, info) == "FastAPI / Uvicorn"
    assert resolver.resolve(8000, info) == "AI Backend"


def test_custom_descriptions_only_apply_to_their_own_port():
    resolver = DescriptionResolver({"8000": "AI Backend"})
    assert resolver.resolve(8001, proc("python.exe")) == "Python process"


def test_custom_descriptions_accept_integer_keys_and_ignore_junk():
    resolver = DescriptionResolver({8000: "AI Backend", "nope": "x", "3000": "   "})
    assert resolver.custom_descriptions == {"8000": "AI Backend"}
